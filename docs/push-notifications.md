# Web push: keys, placement, verification, rotation

Lemely sends payload-less VAPID web push (RFC 8030/8292): the push wakes the
service worker, and the worker asks an open page for the newest unread inbox
row (`web/src/sw.ts`, `web/src/lib/push/`). The inbox row is the notification;
a push is one delivery of it. So a deployment with no keys loses only the
buzz, never a notification. That is why every field of `[push]` defaults to
unset and why no developer machine or CI run needs one.

## 1. Generate

```
lemely push-keygen
lemely --json push-keygen   # machine-readable
```

Prints a P-256 keypair and a paste-ready `[push]` block. It writes no file: the
private key never touches disk through this tool, so there is no half-written
secret to forget about. `--subject` sets the RFC 8292 contact (`mailto:` or
`https:`); default `mailto:support@lemelyig.com`. Use an address somebody
reads: it is how a push service reaches the operator about abuse.

## 2. Place

| Where | Public key | Private key | Subject |
|---|---|---|---|
| Local `lemely.toml` (gitignored) | `[push] vapid_public_key` | `[push] vapid_private_key` | `[push] vapid_subject` |
| Shell | `LEMELY_PUSH__VAPID_PUBLIC_KEY` | `LEMELY_PUSH__VAPID_PRIVATE_KEY` | `LEMELY_PUSH__VAPID_SUBJECT` |
| Deployed (`.github/workflows/deploy.yml`) | repository **variable** `VAPID_PUBLIC_KEY` | repository **secret** `VAPID_PRIVATE_KEY` | literal in the workflow |

The public key is handed to every browser that subscribes (`GET
/api/notifications/push/config`) and is not a secret; the private key is. An
unset secret renders as the empty string in Actions, which the settings loader
reads as unset, so the workflow can merge before the pair exists.

All three are required. A partial configuration is reported as unavailable,
not attempted and rejected by every push service.

## 3. Verify

```
lemely doctor --no-network
```

The `push_transport` check says whether the transport reports itself available
(all three present). It is advisory: it never fails `doctor`, because absent
keys are a supported state. Then, with the app running and signed in, open
Settings > Notifications: the enable-push control appears only when
`/api/notifications/push/config` answers `available: true`. Enable it, and
trigger a notification (post an announcement to a class you are enrolled in,
or wait for the sweeper). The backend logs `push_send_rejected` /
`push_send_failed` with the push service's status if the pair is wrong.

## 4. Rotate

**Rotating the keypair invalidates every stored subscription.** The public key
is baked into each browser subscription as `applicationServerKey`; a push
signed with a different private key is rejected (`401`/`403`) by the push
service, and the browser will not accept a re-subscribe under a new key without
the page asking again. Every user must re-enable push from Settings >
Notifications. That is the one fact that makes rotation an event rather than a
chore: plan it, tell users, and expect `push_subscriptions` to empty and refill.

Rotation steps:

1. `lemely push-keygen` for the new pair.
2. Update the variable and the secret; redeploy.
3. `DELETE FROM push_subscriptions;` on the deployed database (or let the
   404/410 cleanup in `lemely/web/notify.py` evict them one failed push at a
   time, which is slower and noisier).
4. Users re-enable push. The inbox was never affected.

## 5. What is deliberately unchanged when keys are absent

`{ kind: "unavailable" }` in `web/src/lib/push/pushEnable.ts` and the
`unavailable` state in `web/src/portals/settings/NotificationSettings.tsx` are
the correct runtime answer whenever VAPID keys are absent, which is every
developer machine and every CI run. They stop appearing the moment keys are
configured. Do not remove them.
