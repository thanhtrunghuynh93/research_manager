# ADR 0016 — Reads span every workspace you belong to; writes go to one

Status: superseded by [ADR 0020](0020-reads-follow-the-workspace-you-are-in.md) — accepted 2026-09-16
Extends: [ADR 0015](0015-plural-workspace-membership.md), [ADR 0004](0004-application-level-authorization.md)

## Context

ADR 0015 let a professor belong to several workspaces but kept every read inside the one they were
working in. Supervising two labs meant switching between them to see either, and the roll on
`/people` had to be widened by hand with an `across_workspaces` flag — a second, wider variant of a
narrow predicate, which is the shape a permission bug eventually grows in.

`Scope.workspace_id` was answering two questions with one field:

- **Where does this write go?** Creating a project, configuring a calendar, inviting someone: each
  needs exactly one destination.
- **What may this read see?** Not necessarily one workspace, once belonging is plural.

Thirty-three predicates across seven `policies.py` files compared against that single field.

## Decision

**`Scope` gains `workspace_ids`, and every visibility predicate is built on it.**

    workspace_id   — where a write goes. One. Taken from the account.
    workspace_ids  — what a read may see. Every workspace the account belongs to.

The comparison moved into `Scope.within(column)`, and all thirty-three predicates now call it. One
place rather than thirty-three, because widening what a read may see is the most consequential
change anyone can make to this system and it should be visible in one diff.

`workspace_ids` defaults to `{workspace_id}` in `__post_init__`, so a Scope built by hand — a
scheduled job's, a test's — stays single-workspace unless it says otherwise. A job must not span.

A **student's** set is their one membership, so nothing about their access changed. ADR 0004's
single predicate builder is intact: it is still one builder, compiling one rule, and the rule now
reads from a set instead of a value.

Two consequences follow directly and were made explicit rather than left implicit:

- **`GET /users` needs no flag.** The User policy spans because the Scope does, so the roll is one
  read with one predicate. `across_workspaces` is gone.
- **The User policy keys off membership, not `users.workspace_id`.** Those differ under ADR 0015: a
  colleague belonging to a workspace I am in, but working in another of theirs, is on my roll.

## Consequences

- **A professor sees all their workspaces at once, and the screens group by workspace** rather than
  labelling every row. A flat list of two cohorts reads as one cohort.
- **Writes still need a workspace, so "working here" survives.** It is no longer about what you can
  see — only about where what you create lands. That is a smaller idea than it was, and the
  Workspaces screen is the only place it appears.
- **Acting on someone does not span.** `POST /users/{id}/suspend|remove` resolve their target
  through the caller's `workspace_id`, so a student listed under another workspace shows no buttons
  and says to join that workspace. Moving a student is the exception: it names the destination
  explicitly, so it works from anywhere.
- **Leaving a workspace narrows what you can read**, immediately and without a session change,
  because `workspace_ids` is recompiled per request from the membership table.
- **The cost of getting this wrong is now concentrated.** `Scope.within` is one function; an error
  in it is an error everywhere. That is the trade for not having thirty-three copies that could
  drift apart, and it is the reason the widening went there rather than into each policy.
- **`access_epoch` is still the single workspace's.** A cached answer is keyed to the workspace it
  was built for, and a professor reading across several gets one epoch — the one they are working
  in. Nothing today caches a cross-workspace read; if something does, this is where to look first.
