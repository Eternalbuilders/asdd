# Feature Specification: Long, Naturally-Scrollable Session History

**Feature Branch**: `005-scrollback-history`

**Created**: 2026-06-13

**Status**: Draft

**Input**: User description: "There is a problem with scrolling when you have claude open with asdd claude project, you can scroll with shift and mouse, but I often find that the scroll history stops and you can't really see all you need to see. We should have a solution that allows you to scroll with mouse, and have a long history just as if you started claude from the terminal locally"

## Context

When an operator opens an interactive Claude session with `asdd claude <project>` (or
`asdd attach` / `asdd open`), the terminal is joined to a single long-lived session that
is held alive inside the container so it stays mobile/web-visible and locally
re-attachable. Joining that held session means the operator's terminal is no longer
talking directly to Claude — it passes through the session multiplexer that keeps the
process alive. That multiplexer, not the operator's own terminal emulator, now governs
how far back the operator can scroll and how scrolling is triggered.

The consequence the user reports: scrollback is short (older output is discarded before
it can be read) and scrolling feels foreign (it requires modifier-key gymnastics and
abruptly stops). A locally-launched `claude` in a normal terminal does not have this
problem because the terminal emulator itself holds a large scrollback and the mouse
wheel scrolls it natively.

This feature makes the attached session's scrolling and history behave the way it would
in a local terminal: a long retained history and natural mouse-wheel scrolling.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Scroll back through a long session to re-read earlier output (Priority: P1)

An operator working in an `asdd claude` session has produced far more output than fits on
one screen (a long file dump, a verbose test run, a multi-step Claude exchange). They need
to scroll up to re-read something Claude said or a result that has rolled off-screen.

**Why this priority**: This is the reported pain. Without enough retained history the
operator cannot review what just happened, which is core to working in an interactive
session at all.

**Independent Test**: Open `asdd claude <project>`, generate several screens of output,
then scroll up. The operator can reach output produced well beyond the visible screen —
at least as far back as a comparable local terminal session would allow — without history
being truncated.

**Acceptance Scenarios**:

1. **Given** an attached session that has emitted many screens of output, **When** the
   operator scrolls toward the top, **Then** they can review output from much earlier in
   the session rather than hitting an abrupt stop after a short distance.
2. **Given** the operator has scrolled up to read earlier output, **When** they scroll
   back to the bottom (or new output arrives), **Then** the view returns to the live
   session showing the latest output.
3. **Given** a session that has been running and producing output for an extended period,
   **When** the operator scrolls back, **Then** a substantial, predictable amount of
   recent history is still available rather than only the last screen or two.

### User Story 2 - Scroll with the mouse wheel without special key combinations (Priority: P1)

An operator wants to scroll the session history the same way they scroll any terminal
window: by rolling the mouse wheel (or trackpad) up and down.

**Why this priority**: The user explicitly wants scrolling "just as if you started claude
from the terminal locally." Requiring modifier keys (e.g. Shift) or unfamiliar gestures is
the friction being removed; it is as important as the history depth itself.

**Independent Test**: In an attached `asdd claude` session, roll the mouse wheel up. The
view scrolls back through history immediately, with no modifier key held.

**Acceptance Scenarios**:

1. **Given** an attached session, **When** the operator rolls the mouse wheel up, **Then**
   the history scrolls up directly without requiring a modifier key.
2. **Given** the operator has scrolled up with the mouse, **When** they roll the mouse
   wheel down past the latest line, **Then** the view returns to following live output.
3. **Given** the operator scrolls within the session, **When** they reach the top or
   bottom of available history, **Then** scrolling stops cleanly at the boundary without
   erroring or detaching the session.

### User Story 3 - Consistent behaviour across every way of joining the session (Priority: P2)

An operator may join the same long-lived session through more than one entry point
(`asdd claude`, `asdd attach`, `asdd open`). Scrolling and history should feel the same
regardless of which one they used.

**Why this priority**: Inconsistent behaviour between entry points would be confusing and
would partially reintroduce the problem; but the core value is delivered by Stories 1 and
2, so this is secondary.

**Independent Test**: Join the same project session via two different entry points in turn
and confirm that long history and mouse scrolling behave identically in both.

**Acceptance Scenarios**:

1. **Given** the same running project session, **When** the operator joins it via any
   supported entry point, **Then** mouse-wheel scrolling and retained history depth behave
   the same way.

### Edge Cases

- **Copy/paste while scrolling**: When the operator selects text with the mouse to copy
  it, the selection/copy behaviour must remain usable and must not be broken by enabling
  mouse-wheel scrolling.
- **Detach must still work**: Enabling richer scrolling must not interfere with the
  operator's ability to detach and leave the session running (so Claude keeps running and
  stays mobile/web-visible).
- **Mobile/web parity unaffected**: Changes to local scrolling must not change what the
  remote (mobile/web) view sees or how it behaves.
- **Very long-running sessions**: History is necessarily bounded by memory; the system
  must retain a large but finite amount and discard only the oldest output once that bound
  is reached, never failing or slowing the live session.
- **Resized terminal**: Scrolling back after the terminal window has been resized must not
  corrupt or lose access to earlier history.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: An attached interactive Claude session MUST retain a large scrollback
  history so the operator can scroll back through output produced much earlier in the
  session, not merely the last screen or two.
- **FR-002**: The retained history depth MUST be comparable to what an operator would
  expect from a locally-launched terminal session (i.e. thousands of lines, not a couple
  of screens).
- **FR-003**: The operator MUST be able to scroll the session history using the mouse
  wheel / trackpad directly, without holding a modifier key.
- **FR-004**: Scrolling up MUST move into history and scrolling back down (or the arrival
  of new output) MUST return the view to the live, following state.
- **FR-005**: Scrolling MUST stop cleanly at the top and bottom boundaries of available
  history without producing errors or detaching the session.
- **FR-006**: Selecting and copying text with the mouse MUST remain usable after
  mouse-wheel scrolling is enabled.
- **FR-007**: The operator MUST still be able to detach from the session and leave the
  underlying Claude process running (preserving mobile/web visibility and local
  re-attachability).
- **FR-008**: The scrolling and history behaviour MUST be consistent across every
  supported way of joining the session (`asdd claude`, `asdd attach`, `asdd open`).
- **FR-009**: Enabling local scrollback and mouse scrolling MUST NOT open any inbound
  network port or otherwise change the session's outbound-only, no-listener posture.
- **FR-010**: The behaviour MUST apply automatically to project sessions without the
  operator needing to perform manual per-session configuration.

### Key Entities

- **Attached session**: The operator's terminal connection to a project's long-lived
  Claude process. Has properties relevant here: retained history depth and scroll-input
  behaviour.
- **Scrollback history**: The buffer of past session output the operator can scroll back
  through. Bounded in size; oldest output is discarded once the bound is reached.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In an attached session that has produced at least several thousand lines of
  output, the operator can scroll back and read output from at least 2,000 lines earlier
  without it having been discarded.
- **SC-002**: The operator can initiate scrolling with a single mouse-wheel gesture and no
  modifier key, on the first attempt, in 100% of attached sessions.
- **SC-003**: Returning to live output after scrolling requires no special command — it
  happens by scrolling to the bottom or when new output arrives — in 100% of sessions.
- **SC-004**: Operators report that scrolling an `asdd claude` session feels equivalent to
  a locally-launched terminal session, with no reported cases of history "stopping" before
  the expected depth.
- **SC-005**: Enabling the feature introduces zero new inbound ports and zero regressions
  in detach, copy/paste, and mobile/web visibility.

## Assumptions

- The reported behaviour stems from the operator's terminal being joined to a held,
  multiplexed session rather than talking to Claude directly; the multiplexer's defaults
  (short history buffer, modifier-gated scrolling) are the cause, and these are
  configurable.
- "Long history" means a large but finite, memory-bounded buffer; unbounded retention is
  out of scope and undesirable.
- A retained depth on the order of several thousand lines satisfies "just as if you
  started claude from the terminal locally" for this user; an exact line count can be
  tuned during planning.
- This feature concerns only the local operator experience of the attached session; the
  mobile/web remote-control experience is out of scope and must remain unchanged.
- The change applies to project session containers and is delivered as part of the
  standard session setup, requiring no per-operator manual steps.
