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

export function useStoreOrderStatus(orderId: string | undefined, actionToken?: string, enabled = true) {
  return useQuery({
    queryKey: ['store', 'orderStatus', orderId || '', actionToken || ''],
    queryFn: () => storeApi.getOrderStatus(orderId!, actionToken),
    enabled: enabled && !!orderId,
    staleTime: 10 * 1000,
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
    mutationFn: ({
      orderId,
      amount,
      idempotencyKey,
    }: {
      orderId: string;
      amount?: number;
      idempotencyKey?: string;
    }) => storeApi.refundOrder(orderId, amount, idempotencyKey),
    onSuccess: (order) => refresh(order.order_id),
  });
  const invoice = useMutation({
    mutationFn: (orderId: string) => storeApi.sendInvoice(orderId),
    onSuccess: (order) => refresh(order.order_id),
  });
  const voidOrder = useMutation({
    mutationFn: (orderId: string) => storeApi.voidOrder(orderId),
    onSuccess: (order) => refresh(order.order_id),
  });
  const backfillRevelTransaction = useMutation({
    mutationFn: ({ orderId, transactionId }: { orderId: string; transactionId: string }) =>
      storeApi.backfillRevelTransaction(orderId, { revel_transaction_id: transactionId }),
    onSuccess: (_resp, vars) => refresh(vars.orderId),
  });

  return { confirm, fulfill, reject, refund, invoice, voidOrder, backfillRevelTransaction };
}
