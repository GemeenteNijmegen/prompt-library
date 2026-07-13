#!/usr/bin/env bash
#
# Verify keycloak/realm-export.prod.json — the production realm structural
# source of truth (ADR 0007). Automates every check that can be done from the
# CLI so the only remaining manual steps are the genuinely browser-bound ones
# (registering a passkey / entering a TOTP code — see issue #94 AC 2 & 3).
#
# Two layers:
#   1. OFFLINE  — structural assertions on the committed JSON. No Docker/network.
#                 Always runs. Catches malformed flows, a broken browserFlow
#                 binding, missing webAuthn policy, and over-255-char flow
#                 descriptions (Keycloak's DESCRIPTION column is VARCHAR(255)).
#   2. LIVE     — if a scratch Keycloak is reachable at $KC_URL: log in as admin,
#                 assert the imported flow matches intent via the admin REST API,
#                 then provision the `opstest` test user with the CONFIGURE_TOTP
#                 and webauthn-register-passwordless required actions so a human
#                 can immediately exercise the browser login.
#
# Usage:
#   keycloak/verify-prod-realm.sh              # offline + live (if KC_URL up)
#   keycloak/verify-prod-realm.sh --offline    # offline only
#   keycloak/verify-prod-realm.sh --print-docker   # print the scratch-KC command
#
# Env (defaults match keycloak/README.md scratch instance):
#   KC_URL=http://localhost:8081  KC_ADMIN=admin  KC_ADMIN_PW=admin
#   REALM=gallery  TEST_USER=opstest  TEST_USER_PW='Op$Test-2026x'
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REALM_FILE="$REPO_ROOT/keycloak/realm-export.prod.json"

KC_URL="${KC_URL:-http://localhost:8081}"
KC_ADMIN="${KC_ADMIN:-admin}"
KC_ADMIN_PW="${KC_ADMIN_PW:-admin}"
REALM="${REALM:-gallery}"
TEST_USER="${TEST_USER:-opstest}"
# Shell-safe (no $, quotes) and policy-valid: len>=12, upper/lower/digit/special, != username.
TEST_USER_PW="${TEST_USER_PW:-Passw0rd-2026x}"
KC_IMAGE="${KC_IMAGE:-quay.io/keycloak/keycloak:26.6.2}"

green() { printf '\033[32m✓ %s\033[0m\n' "$1"; }
red()   { printf '\033[31m✗ %s\033[0m\n' "$1" >&2; }
info()  { printf '  %s\n' "$1"; }

docker_cmd() {
  cat <<EOF
docker run --rm -p 8081:8080 \\
  -e KC_BOOTSTRAP_ADMIN_USERNAME=$KC_ADMIN -e KC_BOOTSTRAP_ADMIN_PASSWORD=$KC_ADMIN_PW \\
  -v "$REALM_FILE":/opt/keycloak/data/import/realm-export.prod.json:ro \\
  $KC_IMAGE start-dev --import-realm --features=organization
EOF
}

# ---------------------------------------------------------------------------
# Layer 1: offline structural assertions on the committed JSON
# ---------------------------------------------------------------------------
offline_checks() {
  echo "== Offline: keycloak/realm-export.prod.json =="
  python3 - "$REALM_FILE" <<'PY'
import json, sys
path = sys.argv[1]
d = json.load(open(path))
errors = []

def check(cond, msg):
    (print(f"\033[32m  ✓ {msg}\033[0m") if cond
     else (errors.append(msg) or print(f"\033[31m  ✗ {msg}\033[0m")))

flows = {f["alias"]: f for f in d.get("authenticationFlows", [])}

check(d.get("browserFlow") == "gallery-ops-browser",
      "realm browserFlow is bound to gallery-ops-browser")
check("gallery-ops-browser" in flows,
      "gallery-ops-browser flow is defined")

# Keycloak AUTHENTICATION_FLOW.DESCRIPTION is VARCHAR(255) — import fails (SQLState
# 22001) above that. This is the regression guard for the bug fixed in e400385.
for alias, f in flows.items():
    check(len(f.get("description", "")) <= 255,
          f"{alias} description within 255-char DB limit ({len(f.get('description',''))})")

# Every subflow reference resolves; no orphan/dangling flowAlias.
for alias, f in flows.items():
    for e in f.get("authenticationExecutions", []):
        if e.get("authenticatorFlow"):
            check(e.get("flowAlias") in flows,
                  f"{alias}: subflow ref '{e.get('flowAlias')}' resolves")

def reqs(alias):
    """Map provider/subflow -> requirement for a flow's direct executions."""
    out = {}
    for e in flows.get(alias, {}).get("authenticationExecutions", []):
        key = e.get("flowAlias") if e.get("authenticatorFlow") else e.get("authenticator")
        out[key] = e.get("requirement")
    return out

top = reqs("gallery-ops-browser")
check(top.get("auth-cookie") == "ALTERNATIVE", "browser: Cookie is ALTERNATIVE")
check(top.get("identity-provider-redirector") == "ALTERNATIVE",
      "browser: Identity Provider Redirector is ALTERNATIVE")
# Organization subflow must be an ALTERNATIVE sibling *before* forms (mirrors Keycloak's
# default browser flow) so federated users are routed before the local credential path.
check(top.get("gallery-ops-organization") == "ALTERNATIVE", "browser: Organization subflow is ALTERNATIVE")
check(top.get("gallery-ops-forms") == "ALTERNATIVE", "browser: forms subflow is ALTERNATIVE")

org = reqs("gallery-ops-organization")
check(org.get("gallery-ops-conditional-organization") == "CONDITIONAL",
      "organization: conditional-organization wrapper is CONDITIONAL")
condorg = reqs("gallery-ops-conditional-organization")
check(condorg.get("conditional-user-configured") == "REQUIRED",
      "conditional-organization: user-configured condition REQUIRED")
check(condorg.get("organization") == "ALTERNATIVE",
      "conditional-organization: organization authenticator ALTERNATIVE")

forms = reqs("gallery-ops-forms")
check(forms.get("auth-username-form") == "REQUIRED", "forms: identity-first Username Form REQUIRED")
check("organization" not in forms,
      "forms: no bare organization step (it lives in the Organization subflow, not the credential path)")
check(forms.get("gallery-ops-credentials") == "REQUIRED", "forms: credentials subflow REQUIRED")

cred = reqs("gallery-ops-credentials")
check(cred.get("webauthn-authenticator-passwordless") == "ALTERNATIVE",
      "credentials: passkey (WebAuthn passwordless) is an ALTERNATIVE")
check(cred.get("gallery-ops-password-totp") == "ALTERNATIVE",
      "credentials: password+TOTP is the other ALTERNATIVE (not layered)")

ptotp = reqs("gallery-ops-password-totp")
check(ptotp.get("auth-password-form") == "REQUIRED", "password+TOTP: Password Form REQUIRED")
check(ptotp.get("auth-otp-form") == "REQUIRED", "password+TOTP: OTP Form REQUIRED (forced TOTP)")

# Passwordless passkeys need resident key + user verification to be true passkeys.
check(d.get("webAuthnPolicyPasswordlessRequireResidentKey") == "Yes",
      "webAuthn passwordless requires resident key")
check(d.get("webAuthnPolicyPasswordlessUserVerificationRequirement") == "required",
      "webAuthn passwordless requires user verification")

sys.exit(1 if errors else 0)
PY
  green "offline structural checks passed"
}

# ---------------------------------------------------------------------------
# Layer 2: live checks + test-user provisioning against a scratch Keycloak
# ---------------------------------------------------------------------------
kc_up() { curl -fsS --max-time 3 "$KC_URL/realms/master" >/dev/null 2>&1; }

admin_token() {
  curl -fsS -X POST "$KC_URL/realms/master/protocol/openid-connect/token" \
    -d client_id=admin-cli -d grant_type=password \
    -d "username=$KC_ADMIN" -d "password=$KC_ADMIN_PW" | jq -r .access_token
}

live_checks() {
  echo
  echo "== Live: $KC_URL (realm '$REALM') =="
  command -v jq >/dev/null || { red "jq is required for live checks"; exit 1; }
  local tok; tok="$(admin_token)"
  [ -n "$tok" ] && [ "$tok" != "null" ] || { red "could not obtain admin token"; exit 1; }
  green "authenticated to admin REST API"

  local api="$KC_URL/admin/realms/$REALM"
  auth() { curl -fsS -H "Authorization: Bearer $tok" "$@"; }

  # Realm imported at all + flow binding survived import.
  local bf; bf="$(auth "$api" | jq -r .browserFlow)"
  [ "$bf" = "gallery-ops-browser" ] \
    && green "realm imported; browserFlow = gallery-ops-browser" \
    || { red "browserFlow is '$bf', expected gallery-ops-browser"; exit 1; }

  # Flattened execution list, asserting provider -> requirement as imported.
  local execs; execs="$(auth "$api/authentication/flows/gallery-ops-browser/executions")"
  assert_exec() {
    local prov="$1" want="$2"
    local got; got="$(echo "$execs" | jq -r --arg p "$prov" '.[] | select(.providerId==$p) | .requirement' | head -1)"
    [ "$got" = "$want" ] \
      && green "execution $prov = $want" \
      || { red "execution $prov = '${got:-MISSING}', expected $want"; exit 1; }
  }
  assert_exec auth-cookie ALTERNATIVE
  assert_exec identity-provider-redirector ALTERNATIVE
  assert_exec organization ALTERNATIVE
  assert_exec auth-username-form REQUIRED
  assert_exec webauthn-authenticator-passwordless ALTERNATIVE
  assert_exec auth-password-form REQUIRED
  assert_exec auth-otp-form REQUIRED

  # Provision (or refresh) the test user with the enrollment required actions.
  local uid; uid="$(auth "$api/users?username=$TEST_USER&exact=true" | jq -r '.[0].id // empty')"
  local body
  body="$(jq -n --arg u "$TEST_USER" '{
    username:$u, email:($u+"@gallery.local"), enabled:true, emailVerified:true,
    requiredActions:["CONFIGURE_TOTP","webauthn-register-passwordless"]
  }')"
  if [ -z "$uid" ]; then
    curl -fsS -X POST "$api/users" -H "Authorization: Bearer $tok" \
      -H "Content-Type: application/json" -d "$body" >/dev/null
    uid="$(auth "$api/users?username=$TEST_USER&exact=true" | jq -r '.[0].id')"
    green "created test user '$TEST_USER' ($uid)"
  else
    curl -fsS -X PUT "$api/users/$uid" -H "Authorization: Bearer $tok" \
      -H "Content-Type: application/json" -d "$body" >/dev/null
    green "refreshed existing test user '$TEST_USER' ($uid)"
  fi

  # Password via the dedicated reset-password endpoint (more reliable than inline
  # credentials on create, and surfaces policy rejections as a non-2xx).
  curl -fsS -X PUT "$api/users/$uid/reset-password" -H "Authorization: Bearer $tok" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg pw "$TEST_USER_PW" '{type:"password", value:$pw, temporary:false}')" >/dev/null
  green "set password (reset-password)"

  # Gallery Ops accounts are members of the gallery-ops Organisation. Without this the
  # identity-first step resolves the user but the flow has no org context — add it so the
  # login path matches production. Ignore 409 (already a member).
  local orgid; orgid="$(auth "$api/organizations" | jq -r '.[0].id // empty')"
  if [ -n "$orgid" ]; then
    curl -fsS -X POST "$api/organizations/$orgid/members" -H "Authorization: Bearer $tok" \
      -H "Content-Type: application/json" -d "\"$uid\"" >/dev/null 2>&1 \
      && green "added '$TEST_USER' to gallery-ops organization" \
      || info "'$TEST_USER' already a gallery-ops member (or add skipped)"
  fi

  # Clear any brute-force lock from prior failed attempts (a locked account looks like a
  # wrong password at the login screen).
  curl -fsS -X DELETE "$api/attack-detection/brute-force/users/$uid" \
    -H "Authorization: Bearer $tok" >/dev/null 2>&1 || true

  cat <<EOF

── Remaining manual steps (browser-only — AC 2 & 3 of #94) ──────────────────
1. Enable a virtual authenticator: browser DevTools (F12) → ⋮ → More tools →
   WebAuthn → Enable virtual authenticator environment → Add authenticator with
   'Supports resident keys' AND 'Supports user verification' both ON. Keep
   DevTools open. (Or use a real passkey / security key.)
2. Incognito window → $KC_URL/realms/$REALM/account
   Log in as: $TEST_USER / $TEST_USER_PW
   • CONFIGURE_TOTP fires → click "Unable to scan?" for the secret, then:
       oathtool --totp -b "<SECRET>"     # or any authenticator app
     → proves AC 3 (password + TOTP).
   • webauthn-register-passwordless fires → the virtual authenticator captures
     the passkey silently.
3. Sign out, fresh incognito → $KC_URL/realms/$REALM/account → enter $TEST_USER
   (or "Sign in with a passkey"). You should land in with NO password/OTP prompt
   → proves AC 2 (passkey alone).

NOTE: on http://localhost the account-console *page* may 403 on
'?userProfileMetadata=true' right after login. That is a token-audience quirk of
Keycloak's own account console under this realm's gallery-defaults scope — it does
NOT affect the login itself and does not occur for gallery-app in production.
Confirm success from the server log instead: a good login emits
type="LOGIN" (not "LOGIN_ERROR") for username="$TEST_USER".

AC 4 (federated users never reach this flow): add a throwaway organization with a
verified domain + a linked (dummy) IdP in the admin console, then confirm a user
whose email matches that domain is redirected at the Organization step instead of
being asked for a passkey/password.
─────────────────────────────────────────────────────────────────────────────
EOF
}

# ---------------------------------------------------------------------------
main() {
  case "${1:-}" in
    --print-docker) docker_cmd; exit 0 ;;
    --offline)      offline_checks; exit 0 ;;
    "" ) ;;
    *) red "unknown argument: $1"; exit 2 ;;
  esac

  offline_checks
  if kc_up; then
    live_checks
  else
    echo
    info "No Keycloak at $KC_URL — skipping live checks. Start a scratch instance with:"
    echo
    docker_cmd
    echo
    info "then re-run this script (KC_URL=$KC_URL)."
  fi
}
main "$@"
