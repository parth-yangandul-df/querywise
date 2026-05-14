import {
  Stack,
  Title,
  Group,
  Text,
  Badge,
  ActionIcon,
  Tooltip,
  Alert,
  Loader,
  Code,
  Accordion,
} from '@mantine/core';
import { IconStar, IconStarFilled } from '@tabler/icons-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryApi } from '../api/queryApi';
import type { QueryHistory } from '../types/api';

const STATUS_COLORS: Record<string, string> = {
  success: 'green',
  error: 'red',
  pending: 'yellow',
  cancelled: 'gray',
};

export function HistoryPage() {
  const qc = useQueryClient();

  const { data: history, isLoading } = useQuery({
    queryKey: ['queryHistory'],
    queryFn: () => queryApi.history(),
  });

  const favoriteMutation = useMutation({
    mutationFn: (id: string) => queryApi.toggleFavorite(id),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['queryHistory'] }),
  });

  if (isLoading)
    return (
      <Group justify="center" py="xl">
        <Loader />
      </Group>
    );

  return (
    <Stack gap="md">
      <Title order={2}>Query History</Title>

      {(!history || history.length === 0) && (
        <Alert color="blue">No queries yet. Go ask a question!</Alert>
      )}

      {history && history.length > 0 && (
        <Accordion variant="separated">
          {history.map((q: QueryHistory) => (
            <Accordion.Item key={q.id} value={q.id}>
              <Accordion.Control>
                <Group justify="space-between" wrap="nowrap" w="100%">
                  <Group gap="sm" wrap="nowrap" style={{ flex: 1 }}>
                    <Tooltip
                      label={
                        q.is_favorite ? 'Remove favorite' : 'Add favorite'
                      }
                    >
                      <ActionIcon
                        variant="subtle"
                        color="yellow"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          favoriteMutation.mutate(q.id);
                        }}
                      >
                        {q.is_favorite ? (
                          <IconStarFilled size={16} />
                        ) : (
                          <IconStar size={16} />
                        )}
                      </ActionIcon>
                    </Tooltip>
                    <Text size="sm" fw={500} lineClamp={1} style={{ flex: 1 }}>
                      {q.natural_language}
                    </Text>
                  </Group>
                  <Group gap="xs" wrap="nowrap">
                    <Badge
                      size="sm"
                      color={STATUS_COLORS[q.execution_status] ?? 'gray'}
                      variant="light"
                    >
                      {q.execution_status}
                    </Badge>
                    {q.row_count != null && (
                      <Badge size="sm" variant="light" color="gray">
                        {q.row_count} rows
                      </Badge>
                    )}
                    <Text size="xs" c="dimmed" w={140} ta="right">
                      {new Date(q.created_at).toLocaleString()}
                    </Text>
                  </Group>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="sm">
                  {q.final_sql && (
                    <div>
                      <Text size="sm" fw={500} mb={4}>
                        SQL
                      </Text>
                      <Code block>{q.final_sql}</Code>
                    </div>
                  )}
                  {q.error_message && (
                    <Alert color="red" title="Error">
                      {q.error_message}
                    </Alert>
                  )}
                  {q.result_summary && (
                    <div>
                      <Text size="sm" fw={500} mb={4}>
                        Summary
                      </Text>
                      <Text size="sm">{q.result_summary}</Text>
                    </div>
                  )}
                  {q.retry_count > 0 && (
                    <Badge color="yellow" variant="light">
                      {q.retry_count} retries
                    </Badge>
                  )}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      )}
    </Stack>
  );
}
