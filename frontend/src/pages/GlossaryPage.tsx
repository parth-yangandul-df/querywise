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
  Code,
  TagsInput,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { IconPlus, IconTrash, IconEdit, IconUpload, IconSearch } from '@tabler/icons-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { glossaryApi } from '../api/glossaryApi';
import { useConnections } from '../hooks/useConnections';
import { usePagination } from '../hooks/usePagination';
import { TablePagination } from '../components/common/TablePagination';
import { CsvImportModal } from '../components/common/CsvImportModal';
import type { GlossaryTerm } from '../types/api';

export function GlossaryPage() {
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [editingTerm, setEditingTerm] = useState<GlossaryTerm | null>(null);
  const [csvOpen, setCsvOpen] = useState(false);
  const [search, setSearch] = useState('');

  const { data: connections } = useConnections();
  const qc = useQueryClient();

  const connOptions =
    connections?.map((c) => ({ value: c.id, label: c.name })) ?? [];

  useEffect(() => {
    if (!connectionId && connOptions.length > 0) {
      setConnectionId(connOptions[0].value);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connections]);

  const { data: terms, isLoading } = useQuery({
    queryKey: ['glossary', connectionId],
    queryFn: () => glossaryApi.list(connectionId!),
    enabled: !!connectionId,
  });

  const filteredTerms = terms?.filter((t) => {
    const q = search.toLowerCase();
    return (
      t.term.toLowerCase().includes(q) ||
      t.definition.toLowerCase().includes(q) ||
      (t.sql_expression ?? '').toLowerCase().includes(q)
    );
  });

  const { page, setPage, totalPages, total, paged, pageSize } = usePagination(filteredTerms);

  const deleteMutation = useMutation({
    mutationFn: ({ connId, termId }: { connId: string; termId: string }) =>
      glossaryApi.delete(connId, termId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['glossary', connectionId] }),
  });

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Business Glossary</Title>
        <Group gap="xs">
          <Button
            leftSection={<IconUpload size={16} />}
            variant="light"
            onClick={() => setCsvOpen(true)}
            disabled={!connectionId}
          >
            Import CSV
          </Button>
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => setAddOpen(true)}
            disabled={!connectionId}
          >
            Add Term
          </Button>
        </Group>
      </Group>

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
          placeholder="Search terms..."
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

      {terms?.length === 0 && (
        <Alert color="blue">
          No glossary terms yet. Add business terms to improve SQL generation.
        </Alert>
      )}

      {terms && terms.length > 0 && (
        <>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Term</Table.Th>
                <Table.Th>Definition</Table.Th>
                <Table.Th>SQL Expression</Table.Th>
                <Table.Th>Tables</Table.Th>
                <Table.Th w={80}>Actions</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {paged.map((term: GlossaryTerm) => (
                <Table.Tr key={term.id}>
                  <Table.Td>
                    <Text fw={500}>{term.term}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" lineClamp={2}>
                      {term.definition}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Code>{term.sql_expression}</Code>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      {term.related_tables?.map((t) => (
                        <Badge key={t} size="xs" variant="light">
                          {t}
                        </Badge>
                      ))}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      <Tooltip label="Edit">
                        <ActionIcon
                          variant="subtle"
                          size="sm"
                          onClick={() => setEditingTerm(term)}
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
                            if (confirm(`Delete "${term.term}"?`))
                              deleteMutation.mutate({
                                connId: connectionId!,
                                termId: term.id,
                              });
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
        <GlossaryFormModal
          opened={addOpen || !!editingTerm}
          onClose={() => {
            setAddOpen(false);
            setEditingTerm(null);
          }}
          connectionId={connectionId}
          term={editingTerm}
        />
      )}

      {connectionId && (
        <CsvImportModal
          opened={csvOpen}
          onClose={() => setCsvOpen(false)}
          title="Import Glossary Terms from CSV"
          templateFilename="glossary_template.csv"
          columns={[
            { key: 'term', label: 'Term', required: true },
            { key: 'definition', label: 'Definition', required: true },
            { key: 'sql_expression', label: 'SQL Expression', required: true },
            { key: 'related_tables', label: 'Related Tables', required: false, array: true },
            { key: 'related_columns', label: 'Related Columns', required: false, array: true },
          ]}
          onImportRow={(row) => glossaryApi.create(connectionId, row)}
          onComplete={() => qc.invalidateQueries({ queryKey: ['glossary', connectionId] })}
        />
      )}
    </Stack>
  );
}

function GlossaryFormModal({
  opened,
  onClose,
  connectionId,
  term,
}: {
  opened: boolean;
  onClose: () => void;
  connectionId: string;
  term: GlossaryTerm | null;
}) {
  const qc = useQueryClient();
  const isEdit = !!term;

  const form = useForm({
    initialValues: {
      term: '',
      definition: '',
      sql_expression: '',
      related_tables: [] as string[],
      related_columns: [] as string[],
    },
  });

  useEffect(() => {
    if (term) {
      form.setValues({
        term: term.term,
        definition: term.definition,
        sql_expression: term.sql_expression ?? '',
        related_tables: term.related_tables ?? [],
        related_columns: term.related_columns ?? [],
      });
    } else {
      form.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [term]);

  const mutation = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      isEdit
        ? glossaryApi.update(connectionId, term!.id, values)
        : glossaryApi.create(connectionId, values),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['glossary', connectionId] });
      notifications.show({
        title: isEdit ? 'Term updated' : 'Term created',
        message: `"${form.values.term}" saved`,
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
      title={isEdit ? 'Edit Glossary Term' : 'Add Glossary Term'}
      size="lg"
    >
      <form onSubmit={form.onSubmit((v) => mutation.mutate(v))}>
        <Stack gap="sm">
          <TextInput label="Term" required {...form.getInputProps('term')} />
          <Textarea
            label="Definition"
            required
            autosize
            minRows={2}
            {...form.getInputProps('definition')}
          />
          <Textarea
            label="SQL Expression"
            required
            placeholder="e.g. exposures.ead or stage = 1"
            autosize
            minRows={2}
            {...form.getInputProps('sql_expression')}
          />
          <TagsInput
            label="Related Tables"
            placeholder="Type table name and press Enter"
            {...form.getInputProps('related_tables')}
          />
          <TagsInput
            label="Related Columns"
            placeholder="Type column name and press Enter"
            {...form.getInputProps('related_columns')}
          />
          <Group justify="flex-end">
            <Button variant="subtle" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              {isEdit ? 'Update' : 'Create'}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
