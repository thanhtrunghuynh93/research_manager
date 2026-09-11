# ADR 0005 — GitHub App as the first repository connector

Status: accepted — 2026-09-11

## Context

REPO-01 requires read-only credentials limited to the selected repositories, private repository
support, and webhooks where available. Personal access tokens are bound to one person's account,
are broad by default, and expire or leak with that person.

## Decision

A GitHub App installed by the professor on chosen repositories with read-only permissions
(contents, pull requests, issues, checks, metadata). Installation tokens are minted per sync run
and never stored. Webhooks are verified with the app secret and deduplicated on the delivery id.
The `RepositoryConnector` protocol keeps GitLab a later drop-in.

## Consequences

- Access is scoped by the installation, not by any student's or the professor's personal token.
- The app private key is the one long-lived secret; it lives in the `.env` file, not the database.
- Self-hosted GitLab in the pilot would make GitLab the first implementation instead (open decision 1).
