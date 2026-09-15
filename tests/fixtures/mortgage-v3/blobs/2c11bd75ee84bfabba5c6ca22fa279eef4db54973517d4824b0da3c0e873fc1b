import { assertMonetarySchema } from '../monetaryContracts/schemaValidation';
import { mortgageSchemas } from '../monetaryContracts/runtimeSchemas';
export function assertMortgageWire(value: unknown, kind: keyof typeof mortgageSchemas) { assertMonetarySchema(value, mortgageSchemas[kind]); }
export function assertMortgageInputs(value: unknown) { assertMonetarySchema(value, mortgageSchemas.definitions.$defs.privateInput); }
