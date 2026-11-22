'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createCollectionRunMutation } from '@vollab/api-types/react-query';
import { problemMessage } from './labels';

/**
 * Dispara a coleta (POST /collection/runs). O engine só enfileira: quem executa é o worker
 * (ADR-08). Depois de criar, invalida tudo o que depende do estado da coleta.
 */
export function useStartCollection(onStarted?: (runId: number) => void) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    ...createCollectionRunMutation(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ predicate: (q) => isCollectionQuery(q.queryKey) });
      onStarted?.(data.run.id);
    },
    onError: () => {
      // 409: já há uma coleta ativa; recarrega para mostrá-la.
      queryClient.invalidateQueries({ predicate: (q) => isCollectionQuery(q.queryKey) });
    },
  });
  const errorMessage = mutation.isError
    ? problemMessage(mutation.error, 'Não foi possível iniciar a coleta.')
    : null;
  return { start: () => mutation.mutate({}), isStarting: mutation.isPending, errorMessage };
}

const COLLECTION_QUERY_IDS = new Set(['getCollectionPending', 'getCollectionRun', 'getCollectionGaps', 'getHealth']);

export function isCollectionQuery(queryKey: readonly unknown[]): boolean {
  const first = queryKey[0];
  return (
    typeof first === 'object' &&
    first !== null &&
    '_id' in first &&
    typeof first._id === 'string' &&
    COLLECTION_QUERY_IDS.has(first._id)
  );
}
