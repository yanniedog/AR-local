function AssertEvidenceParents([string]$Path) {
  $item=[IO.DirectoryInfo]::new([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($Path)))
  while($null -ne $item) {
    if(-not $item.Exists){throw 'Evidence parent directory must already exist.'}
    if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'Evidence parent is a link or reparse point.'}
    $item=$item.Parent
  }
}
