/**
 * natural-path-sdk - Content / Reels Hooks
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { contentApi } from '../api/endpoints';
import { queryKeys } from './queryKeys';

export function useReelsFeed(limit = 30, enabled = true) {
  return useQuery({
    queryKey: queryKeys.content.reels(limit),
    queryFn: () => contentApi.getReelsFeed(limit),
    enabled,
    staleTime: 30 * 1000,
  });
}

export function useContentPosts(
  params?: { type?: string; limit?: number },
  enabled = true
) {
  const key = JSON.stringify(params || {});
  return useQuery({
    queryKey: queryKeys.content.posts(key),
    queryFn: () => contentApi.listPosts(params),
    enabled,
    staleTime: 60 * 1000,
  });
}

export function useContentPostById(postId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.content.detail(postId || ''),
    queryFn: () => contentApi.getById(postId!),
    enabled: !!postId,
    staleTime: 60 * 1000,
  });
}

export function useMarkReelSeen() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (postId: string) => contentApi.markReelSeen(postId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        predicate: (q) =>
          Array.isArray(q.queryKey) &&
          q.queryKey[0] === 'content' &&
          q.queryKey[1] === 'reels',
      });
    },
  });
}

export function useLikeReel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (postId: string) => contentApi.likeReel(postId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        predicate: (q) =>
          Array.isArray(q.queryKey) &&
          q.queryKey[0] === 'content' &&
          q.queryKey[1] === 'reels',
      });
    },
  });
}

export function useUnlikeReel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (postId: string) => contentApi.unlikeReel(postId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        predicate: (q) =>
          Array.isArray(q.queryKey) &&
          q.queryKey[0] === 'content' &&
          q.queryKey[1] === 'reels',
      });
    },
  });
}

export function useReelComments(postId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.content.comments(postId || ''),
    queryFn: () => contentApi.getReelComments(postId!),
    enabled: enabled && !!postId,
    staleTime: 15 * 1000,
  });
}

export function useAddReelComment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ postId, body }: { postId: string; body: string }) =>
      contentApi.addReelComment(postId, body),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.content.comments(vars.postId),
      });
      queryClient.invalidateQueries({
        predicate: (q) =>
          Array.isArray(q.queryKey) &&
          q.queryKey[0] === 'content' &&
          q.queryKey[1] === 'reels',
      });
    },
  });
}
