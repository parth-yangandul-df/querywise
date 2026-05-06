import { useState, useEffect } from 'react';
import {
  Stack,
  Title,
  Button,
  Group,
  Text,
  Table,
  Modal,
  TextInput,
  Textarea,
  Select,
  ActionIcon,
  Tooltip,
  Alert,
  Loader,
  Badge,
  Switch,
  Code,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { IconPlus, IconTrash, IconEdit, IconSearch } from '@tabler/icons-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { sampleQueriesApi } from '../api/glossaryApi';
import { useConnections } from '../hooks/useConnections';
import { usePagination } from '../hooks/usePagination';
import { TablePagination } from '../components/common/TablePagination';
import type { SampleQuery } from '../types/api';

export function SampleQueriesPage() {
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [editingQuery, setEditingQuery] = useState<SampleQuery | null>(null);
  const [search, setSearch] = useState('');

  const { data: connections } = useConnections();
  const qc = useQueryClient();

  const connOptions =
    connections?.map((c) => ({ value: c.id, label: c.name })) ?? [];
  if (!connectionId && connOptions.length > 0) {
    setConnectionId(connOptions[0].value);
  }

  const { data: queries, isLoading } = useQuery({
    queryKey: ['sample-queries', connectionId],
    queryFn: () => sampleQueriesApi.list(connectionId!),
    enabled: !!connectionId,
  });

  const filteredQueries = queries?.filter((q) => {
    const s = search.toLowerCase();
    return (
      q.natural_language.toLowerCase().includes(s) ||
      q.sql_query.toLowerCase().includes(s) ||
      (q.description ?? '').toLowerCase().includes(s) ||
      (q.tags ?? []).some((t) => t.toLowerCase().includes(s))
    );
  });

  const { page, setPage, totalPages, total, paged, pageSize } = usePagination(filteredQueries);

  const deleteMutation = useMutation({
    mutationFn: ({ connId, sqId }: { connId: string; sqId: string }) =>
      sampleQueriesApi.delete(connId, sqId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['sample-queries', connectionId] }),
  });

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Sample Queries</Title>
        <Button
          leftSection={<IconPlus size={16} />}
          onClick={() => setAddOpen(true)}
          disabled={!connectionId}
        >
          Add Query
        </Button>
      </Group>

      <Text size="sm" c="dimmed">
        Validated natural-language ↔ SQL examples used as few-shot context during SQL generation.
      </Text>

      <Group>
        <Select
          label="Connection"
          data={connOptions}
          value={connectionId}
          onChange={setConnectionId}
          w={300}
        />
        <TextInput
          label="Search"
          placeholder="Search queries..."
          leftSection={<IconSearch size={14} />}
          value={search}
          onChange={(e) => { setSearch(e.currentTarget.value); setPage(1); }}
          w={300}
        />
      </Group>

      {isLoading && (
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      )}

      {queries?.length === 0 && (
        <Alert color="blue">
          No sample queries yet. Add validated examples to improve SQL generation accuracy.
        </Alert>
      )}

      {queries && queries.length > 0 && (
        <>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Natural Language</Table.Th>
                <Table.Th>SQL Query</Table.Th>
                <Table.Th>Description</Table.Th>
                <Table.Th>Tags</Table.Th>
                <Table.Th w={60}>Valid</Table.Th>
                <Table.Th w={80}>Actions</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {(paged as SampleQuery[]).map((sq) => (
                <Table.Tr key={sq.id}>
                  <Table.Td maw={260}>
                    <Text size="sm" fw={500} lineClamp={2}>
                      {sq.natural_language}
                    </Text>
                  </Table.Td>
                  <Table.Td maw={360}>
                    <Code block style={{ fontSize: 11, maxHeight: 80, overflow: 'auto' }}>
                      {sq.sql_query}
                    </Code>
                  </Table.Td>
                  <Table.Td maw={200}>
                    <Text size="sm" c="dimmed" lineClamp={2}>
                      {sq.description}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      {sq.tags?.map((t) => (
                        <Badge key={t} size="xs" variant="light">
                          {t}
                        </Badge>
                      ))}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Badge
                      size="xs"
                      color={sq.is_validated ? 'green' : 'gray'}
                      variant="light"
                    >
                      {sq.is_validated ? 'Yes' : 'No'}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      <Tooltip label="Edit">
                        <ActionIcon
                          variant="subtle"
                          size="sm"
                          onClick={() => setEditingQuery(sq)}
                        >
                          <IconEdit size={14} />
                        </ActionIcon>
                      </Tooltip>
                      <Tooltip label="Delete">
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          size="sm"
                          onClick={() => {
                            if (confirm('Delete this sample query?'))
                              deleteMutation.mutate({ connId: connectionId!, sqId: sq.id });
                          }}
                        >
                          <IconTrash size={14} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          <TablePagination
            page={page}
            totalPages={totalPages}
            total={total}
            pageSize={pageSize}
            onChange={setPage}
          />
        </>
      )}

      {connectionId && (
        <SampleQueryFormModal
          opened={addOpen || !!editingQuery}
          onClose={() => {
            setAddOpen(false);
            setEditingQuery(null);
          }}
          connectionId={connectionId}
          query={editingQuery}
        />
      )}
    </Stack>
  );
}

function SampleQueryFormModal({
  opened,
  onClose,
  connectionId,
  query,
}: {
  opened: boolean;
  onClose: () => void;
  connectionId: string;
  query: SampleQuery | null;
}) {
  const qc = useQueryClient();
  const isEdit = !!query;

  const form = useForm({
    initialValues: {
      natural_language: '',
      sql_query: '',
      description: '',
      tags: '' as string,
      is_validated: false,
    },
    validate: {
      natural_language: (v) => (v.trim() ? null : 'Question is required'),
      sql_query: (v) => (v.trim() ? null : 'SQL is required'),
    },
  });

  useEffect(() => {
    if (query) {
      form.setValues({
        natural_language: query.natural_language,
        sql_query: query.sql_query,
        description: query.description ?? '',
        tags: (query.tags ?? []).join(', '),
        is_validated: query.is_validated,
      });
    } else {
      form.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  const mutation = useMutation({
    mutationFn: (values: ReturnType<typeof form.getValues>) => {
      const payload = {
        natural_language: values.natural_language.trim(),
        sql_query: values.sql_query.trim(),
        description: values.description.trim() || null,
        tags: values.tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
        is_validated: values.is_validated,
      };
      return isEdit
        ? sampleQueriesApi.update(connectionId, query!.id, payload)
        : sampleQueriesApi.create(connectionId, payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sample-queries', connectionId] });
      notifications.show({
        title: isEdit ? 'Query updated' : 'Query created',
        message: 'Sample query saved successfully.',
        color: 'green',
      });
      form.reset();
      onClose();
    },
  });

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={isEdit ? 'Edit Sample Query' : 'Add Sample Query'}
      size="xl"
    >
      <form onSubmit={form.onSubmit((v) => mutation.mutate(v))}>
        <Stack gap="sm">
          <Textarea
            label="Natural language question"
            placeholder="e.g. Which resources are currently on bench?"
            required
            autosize
            minRows={2}
            {...form.getInputProps('natural_language')}
          />
          <Textarea
            label="SQL query"
            placeholder="SELECT ..."
            required
            autosize
            minRows={4}
            styles={{ input: { fontFamily: 'monospace', fontSize: 13 } }}
            {...form.getInputProps('sql_query')}
          />
          <TextInput
            label="Description"
            placeholder="Brief description of what this query does"
            {...form.getInputProps('description')}
          />
          <TextInput
            label="Tags (comma-separated)"
            placeholder="e.g. resource, bench, allocation"
            {...form.getInputProps('tags')}
          />
          <Switch
            label="Validated"
            description="Mark as a confirmed correct example for few-shot prompting"
            {...form.getInputProps('is_validated', { type: 'checkbox' })}
          />
          <Group justify="flex-end" mt="sm">
            <Button variant="subtle" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              {isEdit ? 'Save changes' : 'Create'}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
