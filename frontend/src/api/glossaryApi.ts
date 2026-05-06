import { api } from './client';
import type { GlossaryTerm, MetricDefinition, DictionaryEntry, SampleQuery } from '../types/api';

export const glossaryApi = {
  list: (connectionId: string) =>
    api.get<GlossaryTerm[]>(`/connections/${connectionId}/glossary`).then(r => r.data),
  create: (connectionId: string, data: Partial<GlossaryTerm>) =>
    api.post<GlossaryTerm>(`/connections/${connectionId}/glossary`, data).then(r => r.data),
  update: (connectionId: string, termId: string, data: Partial<GlossaryTerm>) =>
    api.put<GlossaryTerm>(`/connections/${connectionId}/glossary/${termId}`, data).then(r => r.data),
  delete: (connectionId: string, termId: string) =>
    api.delete(`/connections/${connectionId}/glossary/${termId}`),
};

export const metricsApi = {
  list: (connectionId: string) =>
    api.get<MetricDefinition[]>(`/connections/${connectionId}/metrics`).then(r => r.data),
  create: (connectionId: string, data: Partial<MetricDefinition>) =>
    api.post<MetricDefinition>(`/connections/${connectionId}/metrics`, data).then(r => r.data),
  update: (connectionId: string, metricId: string, data: Partial<MetricDefinition>) =>
    api.put<MetricDefinition>(`/connections/${connectionId}/metrics/${metricId}`, data).then(r => r.data),
  delete: (connectionId: string, metricId: string) =>
    api.delete(`/connections/${connectionId}/metrics/${metricId}`),
};

export const sampleQueriesApi = {
  list: (connectionId: string) =>
    api.get<SampleQuery[]>(`/connections/${connectionId}/sample-queries`).then(r => r.data),
  create: (connectionId: string, data: Partial<SampleQuery>) =>
    api.post<SampleQuery>(`/connections/${connectionId}/sample-queries`, data).then(r => r.data),
  update: (connectionId: string, sqId: string, data: Partial<SampleQuery>) =>
    api.put<SampleQuery>(`/connections/${connectionId}/sample-queries/${sqId}`, data).then(r => r.data),
  delete: (connectionId: string, sqId: string) =>
    api.delete(`/connections/${connectionId}/sample-queries/${sqId}`),
};

export const dictionaryApi = {
  list: (columnId: string) =>
    api.get<DictionaryEntry[]>(`/columns/${columnId}/dictionary`).then(r => r.data),
  create: (columnId: string, data: Partial<DictionaryEntry>) =>
    api.post<DictionaryEntry>(`/columns/${columnId}/dictionary`, data).then(r => r.data),
  update: (columnId: string, entryId: string, data: Partial<DictionaryEntry>) =>
    api.put<DictionaryEntry>(`/columns/${columnId}/dictionary/${entryId}`, data).then(r => r.data),
  delete: (columnId: string, entryId: string) =>
    api.delete(`/columns/${columnId}/dictionary/${entryId}`),
};
