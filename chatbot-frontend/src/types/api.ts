export interface ChatSession {
  id: string
  connection_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface ChatSessionMessage {
  id: string
  connection_id: string
  session_id: string | null
  natural_language: string
  generated_sql: string | null
  final_sql: string | null
  execution_status: string
  error_message: string | null
  row_count: number | null
  execution_time_ms: number | null
  retry_count: number
  result_summary: string | null
  turn_type: string
  clarification_reason?: string | null
  result_columns?: string[] | null
  result_preview_rows?: unknown[][] | null
  is_favorite: boolean
  created_at: string
}

export interface Connection {
  id: string
  name: string
  connector_type: string
  default_schema: string
  max_query_timeout_seconds: number
  max_rows: number
  is_active: boolean
  has_connection_string: boolean
  last_introspected_at: string | null
  created_at: string
  updated_at: string
  allowed_table_names: string[] | null
}

export interface ConnectionCreate {
  name: string
  connector_type: string
  connection_string: string
  default_schema: string
  max_query_timeout_seconds: number
  max_rows: number
  allowed_table_names?: string[] | null
}

export interface AvailableTable {
  schema_name: string
  table_name: string
}

export interface TableSummary {
  id: string
  schema_name: string
  table_name: string
  table_type: string
  comment: string | null
  row_count_estimate: number | null
  column_count: number
  created_at: string
}

export interface Column {
  id: string
  column_name: string
  data_type: string
  is_nullable: boolean
  is_primary_key: boolean
  default_value: string | null
  comment: string | null
  ordinal_position: number
}

export interface QueryResult {
  id: string
  question: string
  generated_sql: string | null
  final_sql: string | null
  explanation: string | null
  columns: string[]
  column_types: string[]
  rows: unknown[][]
  row_count: number
  execution_time_ms: number | null
  truncated: boolean
  summary: string | null
  highlights: string[]
  suggested_followups: string[]
  llm_provider: string | null
  llm_model: string | null
  retry_count: number
  turn_type: string
  clarification_message: string | null
  clarification_options: string[]
}

export interface QueryHistory {
  id: string
  connection_id: string
  natural_language: string
  generated_sql: string | null
  final_sql: string | null
  execution_status: string
  error_message: string | null
  row_count: number | null
  execution_time_ms: number | null
  retry_count: number
  result_summary: string | null
  is_favorite: boolean
  created_at: string
}

export interface IntrospectionResult {
  tables_found: number
  columns_found: number
  relationships_found: number
}
