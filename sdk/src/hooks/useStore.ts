import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { storeApi } from '../api/endpoints';
import { queryKeys } from './queryKeys';
import type { CreateStoreOrderRequest } from '../types';

export function useStoreProducts(params?: {
  q?: string;
  category?: string;
  page?: number;
  page_size?: number;
}) {
  const cacheKey = JSON.stringify(params || {});
  return useQuery({
    queryKey: queryKeys.store.products(cacheKey),
    queryFn: () => storeApi.getProducts(params),
    staleTime: 60 * 1000,
  });
}

export function useStoreOrder(orderId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.store.orderDetail(orderId || ''),
    queryFn: () => storeApi.getOrder(orderId!),
    enabled: !!orderId,
    staleTime: 30 * 1000,
  });
}

export function useMyStoreOrders() {
  return useQuery({
    queryKey: queryKeys.store.myOrders,
    queryFn: () => storeApi.getMyOrders(),
    staleTime: 30 * 1000,
  });
}

export function usePractitionerStoreOrders(statusFilter?: string) {
  return useQuery({
    queryKey: queryKeys.store.practitionerOrders(statusFilter),
    queryFn: () => storeApi.getPractitionerOrders(statusFilter),
    staleTime: 30 * 1000,
  });
}

export function useSyncStoreProducts() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => storeApi.syncRevelProducts(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['store', 'products'] });
    },
  });
}

export function useUpdateStoreProduct() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ productId, data }: { productId: string; data: Record<string, unknown> }) =>
      storeApi.updateProduct(productId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['store', 'products'] });
    },
  });
}

export function useCreateStoreOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateStoreOrderRequest) => storeApi.createOrder(data),
    onSuccess: (order) => {
      queryClient.setQueryData(queryKeys.store.orderDetail(order.order_id), order);
      queryClient.invalidateQueries({ queryKey: queryKeys.store.myOrders });
    },
  });
}

export function usePayStoreOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      orderId,
      paymentMethod,
      actionToken,
    }: {
      orderId: string;
      paymentMethod: 'card' | 'wallet' | 'manual';
      actionToken?: string;
    }) => storeApi.payOrder(orderId, paymentMethod, actionToken),
    onSuccess: (order) => {
      queryClient.setQueryData(queryKeys.store.orderDetail(order.order_id), order);
      queryClient.invalidateQueries({ queryKey: queryKeys.store.myOrders });
      queryClient.invalidateQueries({ queryKey: queryKeys.store.practitionerOrders() });
    },
  });
}

export function useSendSmsPayLink() {
  return useMutation({
    mutationFn: ({ orderId, actionToken }: { orderId: string; actionToken?: string }) =>
      storeApi.sendSmsPayLink(orderId, actionToken),
  });
}

export function useStoreOrderOps() {
  const queryClient = useQueryClient();
  const refresh = (orderId: string) => {
    queryClient.invalidateQueries({ queryKey: queryKeys.store.orderDetail(orderId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.store.practitionerOrders() });
    queryClient.invalidateQueries({ queryKey: queryKeys.store.myOrders });
  };

  const confirm = useMutation({
    mutationFn: ({ orderId, reason }: { orderId: string; reason?: string }) =>
      storeApi.confirmOrder(orderId, reason),
    onSuccess: (order) => refresh(order.order_id),
  });
  const fulfill = useMutation({
    mutationFn: ({ orderId, reason }: { orderId: string; reason?: string }) =>
      storeApi.fulfillOrder(orderId, reason),
    onSuccess: (order) => refresh(order.order_id),
  });
  const reject = useMutation({
    mutationFn: ({ orderId, reason }: { orderId: string; reason: string }) =>
      storeApi.rejectOrder(orderId, reason),
    onSuccess: (order) => refresh(order.order_id),
  });
  const refund = useMutation({
    mutationFn: ({ orderId, amount }: { orderId: string; amount?: number }) =>
      storeApi.refundOrder(orderId, amount),
    onSuccess: (order) => refresh(order.order_id),
  });
  const invoice = useMutation({
    mutationFn: (orderId: string) => storeApi.sendInvoice(orderId),
    onSuccess: (order) => refresh(order.order_id),
  });

  return { confirm, fulfill, reject, refund, invoice };
}
