# Mac Sparkle signing key setup (one-time, per-machine)

Fluent's Mac auto-updates are signed with a Sparkle EdDSA keypair, generated
once and stored in this machine's login Keychain. `release.sh` reads it via
Sparkle's `sign_update` CLI at publish time — no password to manage
separately.

## If this Mac is ever replaced

1. Download the Sparkle CLI tools (`generate_keys`, `sign_update`,
   `generate_appcast`) from
   https://github.com/sparkle-project/Sparkle/releases — grab the
   `Sparkle-X.Y.Z.tar.xz` asset (not the SPM zip), and extract `bin/`.
2. Run `generate_keys` once. It stores the private key in the login
   Keychain automatically.
3. Update `SUPublicEDKey` in `fluent/Fluent/Info.plist` with the newly
   printed public key.

**Do not generate a new keypair if the old Keychain/Mac is still
available** — every app already in the wild trusts the original public key
baked into its `Info.plist`. A new keypair breaks auto-updates for everyone
already installed; they'd need to manually reinstall once more.

## If a release aborts partway through

`release.sh` stamps `fluent/Fluent/Info.plist` with the new version/build
number before it builds, but only commits and pushes at the very end. If
notarization or the final publish step fails, that stamp is left as an
uncommitted local change. Before re-running the release, discard it so the
build number doesn't get bumped twice for one published release:

```bash
git checkout fluent/Fluent/Info.plist
```
