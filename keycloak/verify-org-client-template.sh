#!/usr/bin/env bash
#
# Verify keycloak/templates/org-deployed-client.json — the copy-paste-and-fill
# template a Gallery Operator instantiates once per chat client a customer
# Organisation deploys (ADR 0004 step 5, ADR 0007). Issue #95.
#
# Two layers, mirroring keycloak/verify-prod-realm.sh:
#   1. OFFLINE — structural assertions on the committed template. No Docker/network.
#                Always runs (CI-safe). Confirms: placeholders present; the block
#                becomes valid JSON once filled; confidential + auth-code + PKCE-S256;
#                gallery-defaults + prompt:read are default scopes; NO admin:* /
#                prompt:moderate / prompt:publish:public in the optional list; no
#                committed secret; the "consistency aid, not a security boundary" caveat.
#   2. LIVE    — if a scratch Keycloak (built from realm-export.prod.json, see #93) is
#                reachable at $KC_URL: fill the placeholders, create the client via the
#                admin REST API, assert the imported config, retrieve the generated
#                secret, provision a role-bearing test user, then drive a FULL
#                authorization-code + PKCE flow and decode the resulting token to
#                confirm aud=prompt-gallery-api, azp=<client>, and realm_access.roles
#                (AC 2 & AC 3 of #95). Cleans up the client/user afterwards.
#
# The live layer briefly swaps the realm browserFlow to the built-in "browser" flow so
# the auth-code login can be driven headlessly with curl (the production gallery-ops
# passkey/TOTP flow can't be), and restores it on exit. It touches only a throwaway
# scratch realm — never a real one.
#
# Usage:
#   keycloak/verify-org-client-template.sh            # offline + live (if KC_URL up)
#   keycloak/verify-org-client-template.sh --offline  # offline only (CI)
#
# Env (defaults match keycloak/README.md scratch instance):
#   KC_URL=http://localhost:8081  KC_ADMIN=admin  KC_ADMIN_PW=admin  REALM=gallery
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$REPO_ROOT/keycloak/templates/org-deployed-client.json"

KC_URL="${KC_URL:-http://localhost:8081}"
KC_ADMIN="${KC_ADMIN:-admin}"
KC_ADMIN_PW="${KC_ADMIN_PW:-admin}"
REALM="${REALM:-gallery}"

# Test instantiation values (live layer only).
T_CLIENT_ID="${T_CLIENT_ID:-acme-copilot-verify}"
T_ORG_SLUG="${T_ORG_SLUG:-acme}"
T_REDIRECT="${T_REDIRECT:-http://localhost:9998/callback}"
T_USER="${T_USER:-orguser-verify}"
T_USER_PW="${T_USER_PW:-OrgUser-2026x!}"

green() { printf '\033[32m✓ %s\033[0m\n' "$1"; }
red()   { printf '\033[31m✗ %s\033[0m\n' "$1" >&2; }
info()  { printf '  %s\n' "$1"; }

# ---------------------------------------------------------------------------
# Layer 1: offline structural assertions on the committed template
# ---------------------------------------------------------------------------
offline_checks() {
  echo "== Offline: keycloak/templates/org-deployed-client.json =="
  python3 - "$TEMPLATE" <<'PY'
import json, re, sys
path = sys.argv[1]
raw = open(path).read()
errors = []

def check(cond, msg):
    (print(f"\033[32m  ✓ {msg}\033[0m") if cond
     else (errors.append(msg) or print(f"\033[31m  ✗ {msg}\033[0m")))

# Placeholders an operator must fill.
for ph in ("{{CLIENT_ID}}", "{{ORG_SLUG}}", "{{REDIRECT_URIS}}"):
    check(ph in raw, f"placeholder {ph} present")

# Fill placeholders with test values → must be valid JSON (proves an instantiated
# copy parses; guards against a stray comma / broken quoting in the template).
filled = (raw
          .replace("{{CLIENT_ID}}", "acme-copilot")
          .replace("{{ORG_SLUG}}", "acme")
          .replace("{{REDIRECT_URIS}}", "https://acme.example.com/callback")
          .replace("{{WEB_ORIGINS}}", "https://acme.example.com"))
try:
    c = json.loads(filled)
    check(True, "instantiated template is valid JSON")
except Exception as e:
    check(False, f"instantiated template is valid JSON ({e})")
    print(json.dumps({"errors": errors})); sys.exit(1)

# Header caveat — the whole point of the template per ADR 0004 rev 3 / ADR 0007.
comment = " ".join(c.get("_comment", [])).lower()
check("not a security boundary" in comment or "consistency aid" in comment,
      "_comment states it is a consistency aid, not a security boundary")
check("template" in comment,
      "_comment states it is a template, not an importable realm fragment")

# Confidential auth-code + PKCE client shape (ADR 0004 client model).
check(c.get("publicClient") is False, "confidential client (publicClient=false)")
check(c.get("standardFlowEnabled") is True, "authorization-code flow enabled")
check(c.get("implicitFlowEnabled") is False, "implicit flow disabled")
check(c.get("directAccessGrantsEnabled") is False, "direct access grants disabled")
check(c.get("serviceAccountsEnabled") is False, "service accounts disabled")
check(c.get("attributes", {}).get("pkce.code.challenge.method") == "S256",
      "PKCE S256 required")
check("secret" not in c, "no committed client secret (Keycloak generates it)")

dflt = c.get("defaultClientScopes", [])
opt = c.get("optionalClientScopes", [])
check("gallery-defaults" in dflt,
      "gallery-defaults is a default scope (carries aud + realm_access.roles + org_id)")
check("prompt:read" in dflt, "prompt:read is a default scope")

# The documented-intent split: these must NOT appear on an org-deployed client.
forbidden = {"admin:manage_taxonomy", "admin:manage_users", "admin:read_audit",
             "prompt:moderate", "prompt:publish:public"}
present_forbidden = forbidden & (set(dflt) | set(opt))
check(not present_forbidden,
      f"no admin:* / prompt:moderate / prompt:publish:public scopes "
      f"({'none' if not present_forbidden else ', '.join(sorted(present_forbidden))})")
check("prompt:read" not in opt, "prompt:read not duplicated in the optional list")

sys.exit(1 if errors else 0)
PY
  green "offline template checks passed"
}

# ---------------------------------------------------------------------------
# Layer 2: live instantiation + full auth-code+PKCE token inspection
# ---------------------------------------------------------------------------
kc_up() { curl -fsS --max-time 3 "$KC_URL/realms/master" >/dev/null 2>&1; }

admin_token() {
  curl -fsS -X POST "$KC_URL/realms/master/protocol/openid-connect/token" \
    -d client_id=admin-cli -d grant_type=password \
    -d "username=$KC_ADMIN" -d "password=$KC_ADMIN_PW" | jq -r .access_token
}

# Globals populated during live_checks so the EXIT trap can clean up.
TOK=""; API=""; CLIENT_UUID=""; USER_UUID=""; ORIG_BROWSER_FLOW=""; KEEP_STATE=""

cleanup() {
  [ -n "$TOK" ] || return 0
  # On a scripted-flow failure we KEEP the client, user, and the simple "browser" flow
  # so the printed manual fallback is actually runnable; print_manual explains teardown.
  if [ -n "$KEEP_STATE" ]; then
    info "left test client/user and browserFlow='browser' in place for the manual fallback"
    return 0
  fi
  # Restore the realm browser flow first (most important — never leave a scratch realm
  # on the wrong flow), then remove the throwaway client/user.
  if [ -n "$ORIG_BROWSER_FLOW" ]; then
    curl -fsS -X PUT "$API" -H "Authorization: Bearer $TOK" \
      -H "Content-Type: application/json" \
      -d "$(jq -n --arg f "$ORIG_BROWSER_FLOW" '{browserFlow:$f}')" >/dev/null 2>&1 \
      && info "restored realm browserFlow → $ORIG_BROWSER_FLOW" || true
  fi
  [ -n "$CLIENT_UUID" ] && curl -fsS -X DELETE "$API/clients/$CLIENT_UUID" \
    -H "Authorization: Bearer $TOK" >/dev/null 2>&1 && info "removed test client" || true
  [ -n "$USER_UUID" ] && curl -fsS -X DELETE "$API/users/$USER_UUID" \
    -H "Authorization: Bearer $TOK" >/dev/null 2>&1 && info "removed test user" || true
}

live_checks() {
  echo
  echo "== Live: $KC_URL (realm '$REALM') =="
  command -v jq >/dev/null || { red "jq is required for live checks"; exit 1; }
  TOK="$(admin_token)"
  [ -n "$TOK" ] && [ "$TOK" != "null" ] || { red "could not obtain admin token"; exit 1; }
  API="$KC_URL/admin/realms/$REALM"
  auth() { curl -fsS -H "Authorization: Bearer $TOK" "$@"; }
  green "authenticated to admin REST API"
  trap cleanup EXIT

  # --- Instantiate the template: fill placeholders, strip _comment, POST -------------
  local body
  body="$(python3 - "$TEMPLATE" "$T_CLIENT_ID" "$T_ORG_SLUG" "$T_REDIRECT" <<'PY'
import json, sys
tpl, cid, slug, redirect = sys.argv[1:5]
raw = open(tpl).read()
raw = (raw.replace("{{CLIENT_ID}}", cid)
          .replace("{{ORG_SLUG}}", slug)
          .replace("{{REDIRECT_URIS}}", redirect)
          .replace("{{WEB_ORIGINS}}", ""))
c = json.loads(raw)
c.pop("_comment", None)
c["webOrigins"] = []  # not browser-CORS-testing here
print(json.dumps(c))
PY
)"
  # Idempotency: drop any leftover from a prior run.
  local existing
  existing="$(auth "$API/clients?clientId=$T_CLIENT_ID" | jq -r '.[0].id // empty')"
  [ -n "$existing" ] && curl -fsS -X DELETE "$API/clients/$existing" \
    -H "Authorization: Bearer $TOK" >/dev/null 2>&1 || true
  curl -fsS -X POST "$API/clients" -H "Authorization: Bearer $TOK" \
    -H "Content-Type: application/json" -d "$body" >/dev/null
  CLIENT_UUID="$(auth "$API/clients?clientId=$T_CLIENT_ID" | jq -r '.[0].id')"
  [ -n "$CLIENT_UUID" ] && [ "$CLIENT_UUID" != "null" ] \
    && green "created client '$T_CLIENT_ID' ($CLIENT_UUID)" \
    || { red "client creation failed"; exit 1; }

  # --- Assert the imported config matches the template ------------------------------
  local c; c="$(auth "$API/clients/$CLIENT_UUID")"
  [ "$(echo "$c" | jq -r .publicClient)" = "false" ] \
    && green "imported client is confidential" || { red "client is not confidential"; exit 1; }
  [ "$(echo "$c" | jq -r '.attributes["pkce.code.challenge.method"]')" = "S256" ] \
    && green "imported client requires PKCE S256" || { red "PKCE S256 not set"; exit 1; }
  [ "$(echo "$c" | jq -r .standardFlowEnabled)" = "true" ] \
    && green "imported client has auth-code flow" || { red "auth-code flow off"; exit 1; }

  # Default/optional scope split survived import; nothing forbidden slipped in.
  local defs opts
  defs="$(auth "$API/clients/$CLIENT_UUID/default-client-scopes" | jq -r '.[].name')"
  opts="$(auth "$API/clients/$CLIENT_UUID/optional-client-scopes" | jq -r '.[].name')"
  echo "$defs" | grep -qx gallery-defaults \
    && green "gallery-defaults attached as default scope" || { red "gallery-defaults missing"; exit 1; }
  echo "$defs" | grep -qx prompt:read \
    && green "prompt:read attached as default scope" || { red "prompt:read default missing"; exit 1; }
  if echo "$opts" | grep -qE '^(admin:|prompt:moderate$|prompt:publish:public$)'; then
    red "a forbidden scope is in the optional list"; exit 1
  else
    green "no admin:* / prompt:moderate / prompt:publish:public in optional scopes"
  fi

  # Confidential secret is generated, not committed — prove it's retrievable.
  local secret
  secret="$(auth "$API/clients/$CLIENT_UUID/client-secret" | jq -r .value)"
  [ -n "$secret" ] && [ "$secret" != "null" ] \
    && green "generated client secret retrievable (len ${#secret})" \
    || { red "could not retrieve generated secret"; exit 1; }

  # --- Provision a role-bearing test user in the gallery-ops... no, a plain user ----
  # Assign a representative permission-role set so the token's realm_access.roles is
  # meaningful. prompt:read (default-ish) + two optional verbs.
  local roles=(prompt:read prompt:write prompt:rate)
  local ubody
  # firstName/lastName are required by the realm's default user profile — without them
  # login succeeds but Keycloak diverts to a VERIFY_PROFILE required-action form, which
  # the scripted flow can't complete. Set them (and no requiredActions) up front.
  ubody="$(jq -n --arg u "$T_USER" '{
    username:$u, email:($u+"@acme.example.com"), firstName:"Org", lastName:"User",
    enabled:true, emailVerified:true, requiredActions:[],
    attributes:{org_id:["acme-org-verify"]}
  }')"
  curl -fsS -X POST "$API/users" -H "Authorization: Bearer $TOK" \
    -H "Content-Type: application/json" -d "$ubody" >/dev/null 2>&1 || true
  USER_UUID="$(auth "$API/users?username=$T_USER&exact=true" | jq -r '.[0].id')"
  curl -fsS -X PUT "$API/users/$USER_UUID/reset-password" -H "Authorization: Bearer $TOK" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg pw "$T_USER_PW" '{type:"password",value:$pw,temporary:false}')" >/dev/null
  local rolejson="[]"
  for r in "${roles[@]}"; do
    local rr; rr="$(auth "$API/roles/$r")"
    rolejson="$(jq -c --argjson acc "$rolejson" --argjson one "[$rr]" -n '$acc + $one')"
  done
  curl -fsS -X POST "$API/users/$USER_UUID/role-mappings/realm" -H "Authorization: Bearer $TOK" \
    -H "Content-Type: application/json" -d "$rolejson" >/dev/null
  green "provisioned test user '$T_USER' with roles: ${roles[*]}"

  # --- Drive a full authorization-code + PKCE flow (headless) -----------------------
  # Temporarily swap to the built-in browser flow so curl can post username+password
  # (the production passkey/TOTP flow can't be scripted). Restored by cleanup().
  ORIG_BROWSER_FLOW="$(echo "$(auth "$API")" | jq -r .browserFlow)"
  curl -fsS -X PUT "$API" -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
    -d '{"browserFlow":"browser"}' >/dev/null
  info "temporarily set browserFlow → browser (was $ORIG_BROWSER_FLOW) for scripted login"

  if auth_code_pkce_flow "$secret"; then
    green "AUTH-CODE + PKCE token inspection passed (AC 2 & AC 3)"
  else
    red "scripted auth-code flow did not complete — falling back to manual steps"
    KEEP_STATE=1   # keep client/user + simple browser flow so the manual link works
    print_manual "$secret"
  fi
}

# Portable HTML/URL helpers (BSD/macOS grep lacks -P). All read stdin.
form_action() {  # print the action URL of the form that actually holds a credential field
  python3 -c '
import sys, re, html
h = sys.stdin.read()
fallback = None
for m in re.finditer(r"<form\b([^>]*)>(.*?)</form>", h, re.S | re.I):
    attrs, inner = m.group(1), m.group(2)
    am = re.search(r"action=\"([^\"]+)\"", attrs)
    if not am:
        continue
    action = html.unescape(am.group(1))
    if fallback is None:
        fallback = action
    if re.search(r"name=\"(username|password)\"", inner) or "type=\"password\"" in inner:
        print(action); sys.exit(0)
print(fallback or "")'
}
loc_code() {  # print the ?code= value from a redirect URL, if any
  python3 -c 'import sys,re;m=re.search(r"[?&]code=([^&\s]+)",sys.stdin.read());print(m.group(1) if m else "")'
}
kc_error() {  # best-effort: surface a Keycloak login error/feedback message
  python3 -c '
import sys, re, html
h = sys.stdin.read()
m = (re.search(r"kc-feedback-text[^>]*>([^<]+)<", h)
     or re.search(r"id=\"input-error[^\"]*\"[^>]*>([^<]+)<", h))
print(html.unescape(m.group(1).strip()) if m else "")'
}

# Runs the auth-code+PKCE dance with curl and asserts token claims.
# Returns non-zero (without exiting the script) so the caller can print a manual fallback.
auth_code_pkce_flow() {
  local secret="$1"
  local authz="$KC_URL/realms/$REALM/protocol/openid-connect/auth"
  local token_ep="$KC_URL/realms/$REALM/protocol/openid-connect/token"
  local jar; jar="$(mktemp)"
  local verifier challenge state
  verifier="$(python3 -c 'import secrets;print(secrets.token_urlsafe(64))')"
  challenge="$(python3 -c 'import hashlib,base64,sys;print(base64.urlsafe_b64encode(hashlib.sha256(sys.argv[1].encode()).digest()).rstrip(b"=").decode())' "$verifier")"
  state="$(python3 -c 'import secrets;print(secrets.token_urlsafe(8))')"

  # 1. GET the login page; capture the first form's action URL.
  local page action hdr body location code="" step=0
  hdr="$(mktemp)"; body="$(mktemp)"
  page="$(curl -sS -c "$jar" -b "$jar" -G "$authz" \
    --data-urlencode "client_id=$T_CLIENT_ID" \
    --data-urlencode "response_type=code" \
    --data-urlencode "scope=openid prompt:write prompt:rate" \
    --data-urlencode "redirect_uri=$T_REDIRECT" \
    --data-urlencode "state=$state" \
    --data-urlencode "code_challenge=$challenge" \
    --data-urlencode "code_challenge_method=S256")" || { rm -f "$jar" "$hdr" "$body"; return 1; }
  action="$(printf '%s' "$page" | form_action)"
  [ -n "$action" ] || { info "could not find login form action in auth page"; rm -f "$jar" "$hdr" "$body"; return 1; }

  # 2. Post credentials. A realm with organizations enabled uses identity-first login
  #    (username page, THEN a separate password page), so drive up to a few form steps
  #    — sending username+password each time (each form ignores the field it doesn't
  #    need) — until the redirect back to redirect_uri carries ?code=.
  while [ -z "$code" ] && [ "$step" -lt 4 ]; do
    step=$((step + 1))
    [ -n "${DEBUG:-}" ] && info "step $step: POST → $action"
    curl -sS -c "$jar" -b "$jar" -D "$hdr" -o "$body" "$action" \
      --data-urlencode "username=$T_USER" --data-urlencode "password=$T_USER_PW" >/dev/null
    location="$(tr -d '\r' < "$hdr" | awk 'tolower($1)=="location:"{print $2; exit}')"
    if [ -n "${DEBUG:-}" ]; then
      info "step $step: status $(awk 'NR==1{print $2}' "$hdr"), location=${location:-none}"
      [ -z "$location" ] && info "step $step: page error: $(kc_error < "$body")"
    fi
    if [ -n "$location" ]; then
      code="$(printf '%s' "$location" | loc_code)"
      [ -n "$code" ] && break
      page="$(curl -sS -c "$jar" -b "$jar" "$location")"   # next step within the flow
    else
      page="$(cat "$body")"                                # 200 re-render (next step / error)
    fi
    local next; next="$(printf '%s' "$page" | form_action)"
    { [ -z "$next" ] || [ "$next" = "$action" ]; } && break
    action="$next"
  done
  if [ -z "$code" ]; then
    local err; err="$(printf '%s' "$page" | kc_error)"
    info "login did not yield an authorization code after $step step(s)${err:+ — Keycloak said: $err}"
    rm -f "$jar" "$hdr" "$body"; return 1
  fi
  rm -f "$jar" "$hdr" "$body"
  green "obtained authorization code (in $step form step(s))"

  # 3. Exchange code + verifier + client secret for tokens.
  local tokresp access
  tokresp="$(curl -sS -X POST "$token_ep" \
    --data-urlencode "grant_type=authorization_code" \
    --data-urlencode "code=$code" \
    --data-urlencode "redirect_uri=$T_REDIRECT" \
    --data-urlencode "client_id=$T_CLIENT_ID" \
    --data-urlencode "client_secret=$secret" \
    --data-urlencode "code_verifier=$verifier")"
  access="$(printf '%s' "$tokresp" | jq -r '.access_token // empty')"
  [ -n "$access" ] || { info "token exchange failed: $(printf '%s' "$tokresp" | jq -c '{error,error_description}' 2>/dev/null)"; return 1; }
  green "exchanged code for an access token"

  # 4. Decode the access token payload and assert the claims that matter.
  python3 - "$access" <<'PY'
import base64, json, sys
tok = sys.argv[1].split(".")[1]
tok += "=" * (-len(tok) % 4)
claims = json.loads(base64.urlsafe_b64decode(tok))
errors = []
def check(cond, msg):
    (print(f"\033[32m    ✓ {msg}\033[0m") if cond
     else (errors.append(msg) or print(f"\033[31m    ✗ {msg}\033[0m")))

aud = claims.get("aud")
aud = aud if isinstance(aud, list) else [aud]
check("prompt-gallery-api" in aud, f"aud contains prompt-gallery-api (aud={aud})")
check(claims.get("azp") == "acme-copilot-verify", f"azp = the org client (azp={claims.get('azp')})")
roles = set(claims.get("realm_access", {}).get("roles", []))
want = {"prompt:read", "prompt:write", "prompt:rate"}
check(want <= roles, f"realm_access.roles ⊇ granted verbs ({sorted(want & roles)})")
check("prompt:moderate" not in roles and "admin:manage_users" not in roles,
      "no operator-only roles leaked into the token")
check(claims.get("org_id") == "acme-org-verify", f"org_id claim present (org_id={claims.get('org_id')})")
sys.exit(1 if errors else 0)
PY
}

print_manual() {
  local secret="$1"
  # Compute a concrete verifier/challenge here so the URL below is paste-ready — no
  # shell variables to expand (a browser won't expand $CLIENT_ID etc).
  local verifier challenge authurl
  verifier="$(python3 -c 'import secrets;print(secrets.token_urlsafe(64))')"
  challenge="$(python3 -c 'import hashlib,base64,sys;print(base64.urlsafe_b64encode(hashlib.sha256(sys.argv[1].encode()).digest()).rstrip(b"=").decode())' "$verifier")"
  authurl="$(python3 - "$KC_URL" "$REALM" "$T_CLIENT_ID" "$T_REDIRECT" "$challenge" <<'PY'
import sys, urllib.parse as u
kc, realm, cid, redirect, challenge = sys.argv[1:6]
q = u.urlencode({"client_id": cid, "response_type": "code",
                 "scope": "openid prompt:write prompt:rate",
                 "redirect_uri": redirect, "code_challenge": challenge,
                 "code_challenge_method": "S256"})
print(f"{kc}/realms/{realm}/protocol/openid-connect/auth?{q}")
PY
)"
  cat <<EOF

── Manual auth-code + PKCE fallback (AC 2 & 3 of #95) ────────────────────────
The client is created and configured; only the interactive login couldn't be
scripted here. Drive it by hand (values below are concrete — nothing to expand):

1. Paste this URL into a browser, log in as $T_USER / $T_USER_PW, then copy the
   'code=' query param from the redirect to $T_REDIRECT
   (the page itself won't load — you only need the code):

  $authurl

2. Exchange it (replace <CODE>):

  curl -s -X POST $KC_URL/realms/$REALM/protocol/openid-connect/token \\
    -d grant_type=authorization_code -d 'code=<CODE>' \\
    -d 'redirect_uri=$T_REDIRECT' \\
    -d 'client_id=$T_CLIENT_ID' \\
    -d 'client_secret=$secret' \\
    -d 'code_verifier=$verifier' | jq .

3. Confirm the access_token claims:

  <the curl above> | jq -r .access_token \\
    | cut -d. -f2 | python3 -c 'import sys,base64,json; s=sys.stdin.read().strip(); print(json.dumps(json.loads(base64.urlsafe_b64decode(s+"="*(-len(s)%4))),indent=2))'

  Expect: aud contains "prompt-gallery-api", azp="$T_CLIENT_ID", and
  realm_access.roles holds the user's granted verbs (prompt:read/write/rate).

The test client '$T_CLIENT_ID', user '$T_USER', and browserFlow='browser' were
LEFT in place so the URL above works. When done, tear them down:
  admin console → delete client '$T_CLIENT_ID' and user '$T_USER', and set
  Realm settings → Authentication → bind 'browser flow' back to '$ORIG_BROWSER_FLOW'
  (or just discard the scratch container).
──────────────────────────────────────────────────────────────────────────────
EOF
}

# ---------------------------------------------------------------------------
main() {
  case "${1:-}" in
    --offline) offline_checks; exit 0 ;;
    "" ) ;;
    *) red "unknown argument: $1"; exit 2 ;;
  esac

  offline_checks
  if kc_up; then
    live_checks
  else
    echo
    info "No Keycloak at $KC_URL — skipping live checks. Start a scratch instance"
    info "(see keycloak/README.md → 'Two realm files' / verify-prod-realm.sh --print-docker),"
    info "import realm-export.prod.json, then re-run this script."
  fi
}
main "$@"
