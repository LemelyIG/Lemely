import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import type { DeviceList, DeviceRevoked } from "@/lib/deviceTypes"

/*
 * React-query hooks over `/api/me/devices` (G-11). Follows useMeApi.ts's
 * conventions: one hook per endpoint and no `fallback` passed to `request()` —
 * a failure to read the device list must surface as an error the screen can
 * render, never as a silently empty list. An empty devices list is a claim
 * ("nothing is signed in") that would be false and alarming.
 */

const DEVICES_KEY = ["me", "devices"] as const

export function useDevices(): UseQueryResult<DeviceList, Error> {
  return useQuery({
    queryKey: DEVICES_KEY,
    queryFn: () => request<DeviceList>("/me/devices"),
  })
}

export function useRevokeDevice(): UseMutationResult<
  DeviceRevoked,
  Error,
  string
> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (deviceId: string) =>
      request<DeviceRevoked>(`/me/devices/${deviceId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DEVICES_KEY }),
  })
}
