# JARVIS Control Center — secure remote access plan

No remote-access software or account is installed/configured by this repository.
Control Center remains bound to `127.0.0.1:8765`; direct LAN and public bindings
are rejected by the server.

## Recommended V1: Tailscale Serve (private tailnet only)

After the user installs and signs in to Tailscale on the Windows PC and phone:

1. Enable MagicDNS and HTTPS certificates for the tailnet.
2. Restrict access with a tailnet ACL to the user's phone/account.
3. Review the current Serve CLI syntax with `tailscale serve --help`.
4. Proxy HTTPS to the loopback backend, using the current official equivalent of:

   `tailscale serve --bg 8765`

5. Verify `tailscale serve status` says the URL is available only inside the
   tailnet. Never use Tailscale Funnel for this Control Center.
6. Open the server-printed bootstrap URL once through the private HTTPS hostname;
   the HttpOnly, SameSite session cookie then permits the stable clean URL.

Official references:

- https://tailscale.com/docs/features/tailscale-serve
- https://tailscale.com/docs/reference/tailscale-cli/serve
- https://tailscale.com/docs/how-to/set-up-https-certificates

## Alternatives

- WireGuard: private and strong, but the user must operate peer configuration,
  routing, DNS and an HTTPS reverse proxy/certificate lifecycle.
- Cloudflare Tunnel private networking: outbound-only origin connection and
  identity/device policies are available, but it requires a Cloudflare Zero
  Trust account, client enrollment, tunnel configuration and Access policies.
  A public hostname without an Access allow policy is not acceptable.

## Notifications

Persisted Control Center events and browser Notifications work when the mobile
browser grants notification permission and the page is active. Reliable native
background push while the page is closed requires a service worker plus a push
provider/VAPID credential lifecycle; that external capability is intentionally
not provisioned in V1. No credential or token is ever placed in notification text.
