#include <windows.h>
#include <sddl.h>

#include <algorithm>
#include <cwctype>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

class Handle {
 public:
  Handle() = default;
  explicit Handle(HANDLE value) : value_(value) {}
  ~Handle() { reset(); }
  Handle(const Handle&) = delete;
  Handle& operator=(const Handle&) = delete;
  Handle(Handle&& other) noexcept : value_(other.release()) {}
  Handle& operator=(Handle&& other) noexcept {
    if (this != &other) reset(other.release());
    return *this;
  }
  HANDLE get() const { return value_; }
  HANDLE* put() { reset(); return &value_; }
  explicit operator bool() const { return value_ && value_ != INVALID_HANDLE_VALUE; }
  HANDLE release() { HANDLE result = value_; value_ = nullptr; return result; }
  void reset(HANDLE value = nullptr) {
    if (*this) CloseHandle(value_);
    value_ = value;
  }

 private:
  HANDLE value_ = nullptr;
};

std::runtime_error win_error(const char* operation) {
  DWORD code = GetLastError();
  std::ostringstream message;
  message << operation << " failed with Windows error " << code;
  return std::runtime_error(message.str());
}

std::wstring module_path() {
  std::vector<wchar_t> buffer(512);
  while (true) {
    DWORD size = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (!size) throw win_error("GetModuleFileNameW");
    if (size < buffer.size() - 1) return std::wstring(buffer.data(), size);
    buffer.resize(buffer.size() * 2);
  }
}

std::wstring directory_of(const std::wstring& path) {
  size_t split = path.find_last_of(L"\\/");
  if (split == std::wstring::npos) throw std::runtime_error("launcher path has no directory");
  return path.substr(0, split);
}

std::wstring join(const std::wstring& root, const wchar_t* name) {
  return root + L"\\" + name;
}

void require_plain_path(const std::wstring& path, bool directory) {
  DWORD attributes = GetFileAttributesW(path.c_str());
  if (attributes == INVALID_FILE_ATTRIBUTES) throw win_error("GetFileAttributesW");
  if ((attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
    throw std::runtime_error("trusted launcher path is a reparse point");
  }
  bool is_directory = (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
  if (is_directory != directory) throw std::runtime_error("trusted launcher path type mismatch");
}

std::wstring read_operator_sid(const std::wstring& root) {
  std::wstring path = join(root, L"operator.sid");
  require_plain_path(path, false);
  Handle file(CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                          FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
  if (!file) throw win_error("CreateFileW(operator.sid)");
  LARGE_INTEGER size{};
  if (!GetFileSizeEx(file.get(), &size)) throw win_error("GetFileSizeEx(operator.sid)");
  if (size.QuadPart < 10 || size.QuadPart > 184) throw std::runtime_error("operator.sid size is invalid");
  std::string text(static_cast<size_t>(size.QuadPart), '\0');
  DWORD read = 0;
  if (!ReadFile(file.get(), text.data(), static_cast<DWORD>(text.size()), &read, nullptr) ||
      read != text.size()) {
    throw win_error("ReadFile(operator.sid)");
  }
  if (text.find('\r') != std::string::npos || text.find('\n') != std::string::npos ||
      text.find('\0') != std::string::npos) {
    throw std::runtime_error("operator.sid must contain one ASCII SID without a newline");
  }
  return std::wstring(text.begin(), text.end());
}

std::vector<unsigned char> token_information(HANDLE token, TOKEN_INFORMATION_CLASS kind) {
  DWORD size = 0;
  GetTokenInformation(token, kind, nullptr, 0, &size);
  if (GetLastError() != ERROR_INSUFFICIENT_BUFFER || !size) {
    throw win_error("GetTokenInformation(size)");
  }
  std::vector<unsigned char> value(size);
  if (!GetTokenInformation(token, kind, value.data(), size, &size)) {
    throw win_error("GetTokenInformation(value)");
  }
  return value;
}

Handle current_process_token() {
  Handle token;
  DWORD access = TOKEN_QUERY | TOKEN_DUPLICATE | TOKEN_ASSIGN_PRIMARY | TOKEN_IMPERSONATE;
  if (!OpenProcessToken(GetCurrentProcess(), access, token.put())) {
    throw win_error("OpenProcessToken");
  }
  return token;
}

Handle primary_copy(HANDLE source) {
  Handle primary;
  if (!DuplicateTokenEx(source, MAXIMUM_ALLOWED, nullptr, SecurityImpersonation, TokenPrimary,
                        primary.put())) {
    throw win_error("DuplicateTokenEx(primary)");
  }
  return primary;
}

void lower_integrity_to_medium(HANDLE token) {
  auto current = token_information(token, TokenIntegrityLevel);
  auto* current_label = reinterpret_cast<TOKEN_MANDATORY_LABEL*>(current.data());
  auto* count = GetSidSubAuthorityCount(current_label->Label.Sid);
  DWORD current_rid = *GetSidSubAuthority(current_label->Label.Sid, *count - 1);
  if (current_rid <= SECURITY_MANDATORY_MEDIUM_RID) return;

  PSID medium = nullptr;
  if (!ConvertStringSidToSidW(L"S-1-16-8192", &medium)) {
    throw win_error("ConvertStringSidToSidW(Medium integrity)");
  }
  struct LocalGuard {
    HLOCAL value;
    ~LocalGuard() { if (value) LocalFree(value); }
  } guard{medium};
  TOKEN_MANDATORY_LABEL label{};
  label.Label.Attributes = SE_GROUP_INTEGRITY;
  label.Label.Sid = medium;
  DWORD size = static_cast<DWORD>(sizeof(label) + GetLengthSid(medium));
  if (!SetTokenInformation(token, TokenIntegrityLevel, &label, size)) {
    throw win_error("SetTokenInformation(TokenIntegrityLevel)");
  }
}

Handle restricted_token(HANDLE current) {
  Handle restricted;
  if (!CreateRestrictedToken(current, LUA_TOKEN | DISABLE_MAX_PRIVILEGE, 0, nullptr, 0, nullptr,
                             0, nullptr, restricted.put())) {
    throw win_error("CreateRestrictedToken");
  }
  auto result = primary_copy(restricted.get());
  lower_integrity_to_medium(result.get());
  return result;
}

void require_user_sid(HANDLE token, const std::wstring& expected) {
  PSID expected_sid = nullptr;
  if (!ConvertStringSidToSidW(expected.c_str(), &expected_sid)) {
    throw win_error("ConvertStringSidToSidW");
  }
  struct LocalGuard {
    HLOCAL value;
    ~LocalGuard() { if (value) LocalFree(value); }
  } expected_owner{expected_sid};
  auto info = token_information(token, TokenUser);
  auto* user = reinterpret_cast<TOKEN_USER*>(info.data());
  if (!EqualSid(user->User.Sid, expected_sid)) throw std::runtime_error("restricted token user SID differs");
}

void require_no_admin_membership(HANDLE token) {
  SID_IDENTIFIER_AUTHORITY nt = SECURITY_NT_AUTHORITY;
  PSID administrators = nullptr;
  if (!AllocateAndInitializeSid(&nt, 2, SECURITY_BUILTIN_DOMAIN_RID,
                                DOMAIN_ALIAS_RID_ADMINS, 0, 0, 0, 0, 0, 0,
                                &administrators)) {
    throw win_error("AllocateAndInitializeSid");
  }
  struct SidGuard { PSID value; ~SidGuard() { if (value) FreeSid(value); } } guard{administrators};
  Handle impersonation;
  if (!DuplicateTokenEx(token, TOKEN_QUERY | TOKEN_IMPERSONATE, nullptr, SecurityImpersonation,
                        TokenImpersonation, impersonation.put())) {
    throw win_error("DuplicateTokenEx(impersonation)");
  }
  BOOL member = FALSE;
  if (!CheckTokenMembership(impersonation.get(), administrators, &member)) {
    throw win_error("CheckTokenMembership");
  }
  if (member) throw std::runtime_error("restricted token retains enabled Administrators membership");
}

void require_restricted(HANDLE token) {
  DWORD restricted = 0;
  DWORD returned = 0;
  if (!GetTokenInformation(token, TokenHasRestrictions, &restricted, sizeof(restricted), &returned)) {
    throw win_error("GetTokenInformation(TokenHasRestrictions)");
  }
  if (!restricted) throw std::runtime_error("child token has no restrictions");

  auto integrity = token_information(token, TokenIntegrityLevel);
  auto* label = reinterpret_cast<TOKEN_MANDATORY_LABEL*>(integrity.data());
  auto* count = GetSidSubAuthorityCount(label->Label.Sid);
  DWORD rid = *GetSidSubAuthority(label->Label.Sid, *count - 1);
  if (rid > SECURITY_MANDATORY_MEDIUM_RID) {
    throw std::runtime_error("restricted token integrity is above Medium");
  }

  auto privileges = token_information(token, TokenPrivileges);
  auto* list = reinterpret_cast<TOKEN_PRIVILEGES*>(privileges.data());
  for (DWORD index = 0; index < list->PrivilegeCount; ++index) {
    const auto& item = list->Privileges[index];
    if ((item.Attributes & SE_PRIVILEGE_ENABLED) == 0) continue;
    DWORD length = 0;
    LookupPrivilegeNameW(nullptr, const_cast<LUID*>(&item.Luid), nullptr, &length);
    if (GetLastError() != ERROR_INSUFFICIENT_BUFFER) throw win_error("LookupPrivilegeNameW(size)");
    std::wstring name(length, L'\0');
    if (!LookupPrivilegeNameW(nullptr, const_cast<LUID*>(&item.Luid), name.data(), &length)) {
      throw win_error("LookupPrivilegeNameW(value)");
    }
    name.resize(length);
    if (_wcsicmp(name.c_str(), SE_CHANGE_NOTIFY_NAME) != 0) {
      throw std::runtime_error("restricted token retains an enabled privileged capability");
    }
  }
  require_no_admin_membership(token);
}

void require_write_denied(HANDLE token, const std::wstring& path, bool directory) {
  require_plain_path(path, directory);
  if (!ImpersonateLoggedOnUser(token)) throw win_error("ImpersonateLoggedOnUser");
  DWORD flags = FILE_FLAG_OPEN_REPARSE_POINT;
  if (directory) flags |= FILE_FLAG_BACKUP_SEMANTICS;
  bool writable = false;
  DWORD failure = ERROR_ACCESS_DENIED;
  for (DWORD access : {GENERIC_WRITE, DELETE, WRITE_DAC, WRITE_OWNER}) {
    HANDLE attempted = CreateFileW(path.c_str(), access,
                                   FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                                   OPEN_EXISTING, flags, nullptr);
    failure = GetLastError();
    if (attempted != INVALID_HANDLE_VALUE) {
      CloseHandle(attempted);
      writable = true;
      break;
    }
    if (failure != ERROR_ACCESS_DENIED) break;
  }
  if (!RevertToSelf()) throw win_error("RevertToSelf");
  if (writable) {
    throw std::runtime_error("restricted token can modify a protected launcher dependency");
  }
  if (failure != ERROR_ACCESS_DENIED) {
    throw std::runtime_error("protected dependency write check failed for an unexpected reason");
  }
}

void validate_token(HANDLE token, const std::wstring& root) {
  require_user_sid(token, read_operator_sid(root));
  require_restricted(token);
  require_write_denied(token, root, true);
  for (const wchar_t* name : {L"operator.sid", L"protected.sentinel",
                              L"run_laptop_backup_trusted_child.ps1", L"trusted-child.json"}) {
    require_write_denied(token, join(root, name), false);
  }
  std::wstring probe = join(root, L"probe.enabled");
  if (GetFileAttributesW(probe.c_str()) != INVALID_FILE_ATTRIBUTES) {
    require_write_denied(token, probe, false);
  }
}

std::wstring quote(const std::wstring& value) {
  std::wstring result = L"\"";
  size_t slashes = 0;
  for (wchar_t character : value) {
    if (character == L'\\') { ++slashes; continue; }
    if (character == L'\"') {
      result.append(slashes * 2 + 1, L'\\');
      result.push_back(character);
      slashes = 0;
      continue;
    }
    result.append(slashes, L'\\');
    slashes = 0;
    result.push_back(character);
  }
  result.append(slashes * 2, L'\\');
  result.push_back(L'\"');
  return result;
}

std::vector<wchar_t> minimal_environment() {
  wchar_t windows[MAX_PATH + 1]{};
  UINT length = GetWindowsDirectoryW(windows, MAX_PATH);
  if (!length || length >= MAX_PATH) throw win_error("GetWindowsDirectoryW");
  std::vector<std::wstring> values = {
      L"SystemRoot=" + std::wstring(windows),
      L"SystemDrive=" + std::wstring(windows, 2),
      L"TEMP=" + std::wstring(windows) + L"\\Temp",
      L"TMP=" + std::wstring(windows) + L"\\Temp",
      L"WINDIR=" + std::wstring(windows),
  };
  // Retain only identity/profile locations needed by OpenSSH and normal user
  // data lookup.  PATH and all code-selection variables are intentionally not
  // inherited; the protected child constructs its authenticated PATH.
  for (const wchar_t* name : {L"APPDATA", L"HOME", L"HOMEDRIVE", L"HOMEPATH",
                              L"LOCALAPPDATA", L"USERDOMAIN", L"USERNAME", L"USERPROFILE"}) {
    DWORD needed = GetEnvironmentVariableW(name, nullptr, 0);
    if (!needed) continue;
    std::wstring value(needed - 1, L'\0');
    if (GetEnvironmentVariableW(name, value.data(), needed) != needed - 1) {
      throw win_error("GetEnvironmentVariableW");
    }
    values.push_back(std::wstring(name) + L"=" + value);
  }
  std::sort(values.begin(), values.end());
  std::vector<wchar_t> block;
  for (const auto& value : values) {
    block.insert(block.end(), value.begin(), value.end());
    block.push_back(L'\0');
  }
  block.push_back(L'\0');
  return block;
}

DWORD wait_for(PROCESS_INFORMATION& process) {
  Handle thread(process.hThread);
  Handle child(process.hProcess);
  if (WaitForSingleObject(child.get(), INFINITE) != WAIT_OBJECT_0) throw win_error("WaitForSingleObject");
  DWORD code = 1;
  if (!GetExitCodeProcess(child.get(), &code)) throw win_error("GetExitCodeProcess");
  return code;
}

DWORD create_as(HANDLE token, const std::wstring& application, std::wstring command,
                const std::wstring& working_directory) {
  auto environment = minimal_environment();
  STARTUPINFOW startup{};
  startup.cb = sizeof(startup);
  // Do not inherit the privileged parent's window station and desktop.  An
  // empty desktop name asks Windows to connect the restricted child to the
  // noninteractive station selected for its logon session.
  wchar_t noninteractive_desktop[] = L"";
  startup.lpDesktop = noninteractive_desktop;
  PROCESS_INFORMATION process{};
  if (!CreateProcessAsUserW(token, application.c_str(), command.data(), nullptr, nullptr, FALSE,
                            CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT, environment.data(),
                            working_directory.c_str(), &startup, &process)) {
    throw win_error("CreateProcessAsUserW");
  }
  return wait_for(process);
}

DWORD create_inherited(const std::wstring& application, std::wstring command,
                       const std::wstring& working_directory) {
  auto environment = minimal_environment();
  STARTUPINFOW startup{};
  startup.cb = sizeof(startup);
  PROCESS_INFORMATION process{};
  if (!CreateProcessW(application.c_str(), command.data(), nullptr, nullptr, FALSE,
                      CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT, environment.data(),
                      working_directory.c_str(), &startup, &process)) {
    throw win_error("CreateProcessW");
  }
  return wait_for(process);
}

DWORD restricted_child() {
  std::wstring self = module_path();
  std::wstring root = directory_of(self);
  require_plain_path(root, true);
  auto token = current_process_token();
  validate_token(token.get(), root);

  wchar_t system[MAX_PATH + 1]{};
  UINT length = GetSystemDirectoryW(system, MAX_PATH);
  if (!length || length >= MAX_PATH) throw win_error("GetSystemDirectoryW");
  std::wstring powershell = std::wstring(system) + L"\\WindowsPowerShell\\v1.0\\powershell.exe";
  std::wstring script = join(root, L"run_laptop_backup_trusted_child.ps1");
  std::wstring config = join(root, L"trusted-child.json");
  require_plain_path(powershell, false);
  require_plain_path(script, false);
  require_plain_path(config, false);
  std::wstring command = quote(powershell) + L" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " +
                         quote(script) + L" -ConfigPath " + quote(config);
  return create_inherited(powershell, command, root);
}

DWORD restricted_probe() {
  std::wstring root = directory_of(module_path());
  auto token = current_process_token();
  validate_token(token.get(), root);
  return 0;
}

DWORD parent(const std::vector<std::wstring>& child_arguments) {
  std::wstring self = module_path();
  std::wstring root = directory_of(self);
  require_plain_path(root, true);
  auto current = current_process_token();
  auto limited = restricted_token(current.get());
  validate_token(limited.get(), root);
  std::wstring command = quote(self);
  for (const auto& argument : child_arguments) command += L" " + quote(argument);
  return create_as(limited.get(), self, command, root);
}

DWORD scheduled_parent() {
  std::wstring root = directory_of(module_path());
  std::wstring probe = join(root, L"probe.enabled");
  if (GetFileAttributesW(probe.c_str()) != INVALID_FILE_ATTRIBUTES) {
    require_plain_path(probe, false);
    return parent({L"--restricted-probe"});
  }
  return parent({L"--restricted-child"});
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  try {
    if (argc == 1) return static_cast<int>(scheduled_parent());
    if (argc == 2 && std::wstring(argv[1]) == L"--restricted-child") {
      return static_cast<int>(restricted_child());
    }
    if (argc == 2 && std::wstring(argv[1]) == L"--probe") {
#ifdef AR_LAUNCHER_TESTING
      return static_cast<int>(parent({L"--restricted-probe"}));
#else
      std::cerr << "trusted launcher accepts no operator-supplied command\n";
      return 64;
#endif
    }
    if (argc == 2 && std::wstring(argv[1]) == L"--restricted-probe") {
      std::wstring root = directory_of(module_path());
      require_plain_path(join(root, L"probe.enabled"), false);
      return static_cast<int>(restricted_probe());
    }
    std::cerr << "trusted launcher accepts no operator-supplied command\n";
    return 64;
  } catch (const std::exception& error) {
    std::cerr << "trusted launcher failed: " << error.what() << "\n";
    return 1;
  }
}
