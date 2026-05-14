import { useState, useMemo, useEffect } from 'react';
import {
  Stack,
  Title,
  Textarea,
  Button,
  Group,
  Select,
  Paper,
  Text,
  Table,
  Badge,
  Alert,
  Loader,
  Code,
  Accordion,
  CopyButton,
  ActionIcon,
  Tooltip,
  TextInput,
  UnstyledButton,
} from '@mantine/core';
import {
  IconSend,
  IconCopy,
  IconCheck,
  IconAlertCircle,
  IconSearch,
  IconArrowsSort,
  IconArrowUp,
  IconArrowDown,
  IconDownload,
} from '@tabler/icons-react';
import { useMutation } from '@tanstack/react-query';
import { queryApi } from '../api/queryApi';
import { useConnections } from '../hooks/useConnections';
import { usePagination } from '../hooks/usePagination';
import { TablePagination } from '../components/common/TablePagination';
import type { QueryResult } from '../types/api';

export function QueryPage() {
  const [question, setQuestion] = useState('');
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResult | null>(null);

  const { data: connections, isLoading: loadingConns } = useConnections();

  const queryMutation = useMutation({
    mutationFn: () =>
      queryApi.execute({ connection_id: connectionId!, question }),
    onSuccess: (data) => {
      setResult(data);
    },
  });

  const connOptions =
    connections?.map((c) => ({ value: c.id, label: c.name })) ?? [];

  // Auto-select first connection
  if (!connectionId && connOptions.length > 0) {
    setConnectionId(connOptions[0].value);
  }

  const handleRunQuery = () => {
    setResult(null);
    queryMutation.mutate();
  };

  return (
    <Stack gap="md">
      <Title order={2}>Ask a Question</Title>

      <Group align="flex-end">
        <Select
          label="Database connection"
          placeholder="Select connection..."
          data={connOptions}
          value={connectionId}
          onChange={setConnectionId}
          disabled={loadingConns}
          w={300}
        />
      </Group>

      <Textarea
        placeholder="e.g. Show active resources"
        autosize
        minRows={2}
        maxRows={6}
        value={question}
        onChange={(e) => setQuestion(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            if (connectionId && question.trim()) handleRunQuery();
          }
        }}
      />

      <Group>
        <Button
          leftSection={<IconSend size={16} />}
          onClick={handleRunQuery}
          loading={queryMutation.isPending}
          disabled={!connectionId || !question.trim()}
        >
          Run Query
        </Button>
      </Group>

      {queryMutation.isError && (
        <Alert
          color="red"
          icon={<IconAlertCircle size={16} />}
          title="Query failed"
        >
          {(queryMutation.error as Error).message}
        </Alert>
      )}

      {queryMutation.isPending && (
        <Group justify="center" py="xl">
          <Loader size="lg" />
          <Text>Running query...</Text>
        </Group>
      )}

      {result && <QueryResultView result={result} />}
    </Stack>
  );
}

function exportCsv(columns: string[], rows: unknown[][]) {
  const escape = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const header = columns.map(escape).join(',');
  const body = rows.map((r) => (r as unknown[]).map(escape).join(',')).join('\n');
  const blob = new Blob([header + '\n' + body], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `results_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function QueryResultView({ result }: { result: QueryResult }) {
  const [q, setQ] = useState('');
  const [sortCol, setSortCol] = useState<number | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc' | null>(null);

  const lower = q.toLowerCase();

  function cycleSort(colIdx: number) {
    if (sortCol !== colIdx) {
      setSortCol(colIdx);
      setSortDir('asc');
    } else if (sortDir === 'asc') {
      setSortDir('desc');
    } else {
      setSortCol(null);
      setSortDir(null);
    }
  }

  const sortedRows = useMemo(() => {
    if (sortCol === null || sortDir === null) return result.rows;
    return [...result.rows].sort((a, b) => {
      const av = (a as unknown[])[sortCol];
      const bv = (b as unknown[])[sortCol];
      const an = Number(av);
      const bn = Number(bv);
      const numeric = !isNaN(an) && !isNaN(bn);
      const cmp = numeric ? an - bn : String(av ?? '').localeCompare(String(bv ?? ''));
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [result.rows, sortCol, sortDir]);

  // Global filter — applied across ALL rows before pagination
  const filteredRows = useMemo(() => {
    if (!lower) return sortedRows;
    return sortedRows.filter((row) =>
      (row as unknown[]).some((cell) =>
        String(cell ?? '').toLowerCase().includes(lower),
      ),
    );
  }, [sortedRows, lower]);

  const { page, setPage, totalPages, total, paged, pageSize } = usePagination(filteredRows);

  // Reset to page 1 whenever the search term changes
  useEffect(() => {
    setPage(1);
  }, [q, setPage]);

  return (
    <Stack gap="md">
      {result.summary && (
        <Paper withBorder p="md" bg="blue.0">
          <Text fw={600} mb="xs">
            Summary
          </Text>
          <Text>{result.summary}</Text>
        </Paper>
      )}

      <Accordion variant="contained">
        <Accordion.Item value="sql">
          <Accordion.Control>
            <Group>
              <Text fw={500}>SQL</Text>
              <Badge size="sm" variant="light" color="gray">
                {result.row_count} rows
              </Badge>
              {result.llm_provider === 'domain_tool' ? (
                <Badge size="sm" color="green" variant="filled">
                  domain tool
                </Badge>
              ) : (
                <Badge size="sm" color="violet" variant="light">
                  LLM generated
                </Badge>
              )}
              {result.retry_count > 0 && (
                <Badge size="sm" color="yellow">
                  {result.retry_count} retries
                </Badge>
              )}
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <Group justify="flex-end" mb="xs">
              <CopyButton value={result.final_sql}>
                {({ copied, copy }) => (
                  <Tooltip label={copied ? 'Copied' : 'Copy'}>
                    <ActionIcon variant="subtle" onClick={copy}>
                      {copied ? (
                        <IconCheck size={16} />
                      ) : (
                        <IconCopy size={16} />
                      )}
                    </ActionIcon>
                  </Tooltip>
                )}
              </CopyButton>
            </Group>
            <Code block>{result.final_sql}</Code>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      {result.rows.length > 0 && !(result.rows.length === 1 && result.columns.length === 1) && (
        <Paper withBorder p="sm">
          {/* Toolbar: search + match counter + export */}
          <Group mb="sm" gap="xs" align="center" justify="space-between">
            <Group gap="xs" align="center">
              <TextInput
                leftSection={<IconSearch size={14} />}
                placeholder="Filter rows..."
                value={q}
                onChange={(e) => setQ(e.currentTarget.value)}
                size="sm"
                w={280}
              />
              {lower && (
                <Text size="xs" c="dimmed">
                  {filteredRows.length} of {result.rows.length} rows match
                </Text>
              )}
            </Group>
            <Button
              variant="default"
              size="sm"
              leftSection={<IconDownload size={14} />}
              onClick={() => exportCsv(result.columns, result.rows)}
            >
              Export CSV
            </Button>
          </Group>

          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                {result.columns.map((col, colIdx) => (
                  <Table.Th key={col} style={{ whiteSpace: 'nowrap' }}>
                    <UnstyledButton
                      onClick={() => cycleSort(colIdx)}
                      style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                    >
                      <Text size="sm" fw={600}>{col}</Text>
                      {sortCol === colIdx && sortDir === 'asc' ? (
                        <IconArrowUp size={14} />
                      ) : sortCol === colIdx && sortDir === 'desc' ? (
                        <IconArrowDown size={14} />
                      ) : (
                        <IconArrowsSort size={14} style={{ opacity: 0.4 }} />
                      )}
                    </UnstyledButton>
                  </Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {paged.map((row, i) => {
                const rowArr = row as unknown[];
                return (
                  <Table.Tr key={i} bg={lower ? 'teal.0' : undefined}>
                    {rowArr.map((cell, j) => (
                      <Table.Td key={j}>
                        {cell === null ? (
                          <Text c="dimmed" fs="italic" size="sm">
                            null
                          </Text>
                        ) : (
                          String(cell)
                        )}
                      </Table.Td>
                    ))}
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
          <TablePagination
            page={page}
            totalPages={totalPages}
            total={total}
            pageSize={pageSize}
            onChange={setPage}
          />
          {result.truncated && (
            <Text size="sm" c="dimmed" ta="center" pt="xs">
              Results truncated to {result.row_count} rows by server limit
            </Text>
          )}
        </Paper>
      )}

      {result.suggested_followups.length > 0 && (
        <Paper withBorder p="md">
          <Text fw={600} mb="xs">
            Suggested follow-up questions
          </Text>
          <Stack gap="xs">
            {result.suggested_followups.map((q, i) => (
              <Text key={i} size="sm" c="blue">
                {q}
              </Text>
            ))}
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}
