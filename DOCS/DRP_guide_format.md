# DRP Guide Format

DRP means **Direct Run Path**. A DRP guide keeps the normal operator path clean
and puts alternatives, debug commands, and fix procedures in a reference section
at the bottom.

Use this format for setup guides, quickstarts, runbooks, and other documents
that an operator may follow line-by-line while hardware is running.

## Goals

- keep the normal run path short, ordered, and calm
- avoid interrupting a successful run with large blocks of `if this happens`
  logic
- make failure branches easy to find when something does go wrong
- let operators return to the exact step they were running
- make future edits safer by keeping normal-path commands separate from
  troubleshooting commands

## Required Structure

Every DRP guide should use this structure:

```text
# Guide Title

Purpose / status / prerequisites

# Direct Run Path

## Step 0: ...
normal command(s)
expected success signal(s)

### IF specific condition happens
Go to [Fix Step 0.1](#ref-0-1), then return to [Step 0](#step-0).

## Step 1: ...

# Alternative/Debug/Fix Reference

<a id="ref-0-1"></a>
## Fix Step 0.1: Specific Condition
diagnostic or repair commands
Then return to [Step 0](#step-0).
```

## Direct Run Path Rules

- Include only commands the operator should run during a normal successful
  execution.
- Keep each step focused on one job.
- Put expected success signals immediately after the command block.
- Use concrete step names such as `Step 3: Start Local FPV UI`.
- Label command blocks by machine/context before each `bash` block.
- Use `### IF...` headings for every branch out of the direct path.
- Do not place full troubleshooting commands in the direct path.
- Do not place optional modes in the direct path unless they are truly part of
  the normal run.

## `### IF...` Callout Rules

Every direct-path branch should start with `### IF`.

Good examples:

- `### IF dependency install/check fails`
- `### IF robots are visible but read-only/untrusted`
- `### IF wheels move but direction/order is wrong`
- `### IF you need balanced fleet, switch-heavy, all-stream, or LAN-bind mode`

Each callout should contain only:

- the condition
- a link to the reference section
- a return instruction

Example:

```text
### IF robots are visible but read-only/untrusted

Go to [Fix Step 3.2](#ref-3-2), then return to [Step 3](#step-3).
```

## Reference Section Rules

The bottom section should contain all alternatives, diagnostics, and fixes.

Use these prefixes:

- `Fix Step N.M`: for errors and failed checks
- `Alternative Step N.M`: for optional modes or non-default paths
- `Optional`: for standalone optional procedures that are not part of a direct
  step

Every reference entry should:

- start with an anchor such as `<a id="ref-3-2"></a>`
- explain when to use it
- include commands only for that condition
- end with a return instruction such as `Then return to [Step 3](#step-3).`

## Machine Labels

Every shell command block should be immediately preceded by a context label.

Preferred labels:

- `### CONTROL MACHINE:`
- `### ROBOT(S):`

Use other labels only when the distinction is essential, such as:

- `### AFFECTED ROBOT:`
- `### SECOND ROBOT SSH TERMINAL:`

## Readiness and Trust Language

Do not say a robot is ready for live control until the control machine can
recognize and trust it.

For `swarm_control_core`, that means:

- robot-local profile generation can say the local profile is prepared
- control-machine registration/approval can say the robot is ready for
  Quickstart handoff
- FPV UI readiness requires the robot to be present in the trusted
  control-machine `robot_instances.yaml`

Bad:

```text
[OK] This robot is ready for QUICKSTART.
```

Good, on the robot:

```text
[OK] Local robot profile is prepared on this robot.
[NEXT] Register/approve this robot on the control machine before expecting FPV UI control.
```

Good, after control-machine approval:

```text
[OK] Registered/approved robots are ready for QUICKSTART handoff.
```

## Editing Checklist

Before finishing a DRP guide edit, check:

- the direct path can be followed top-to-bottom without reading the fix section
- every branch in the direct path starts with `### IF`
- every `### IF` callout links to a real reference anchor
- every reference entry tells the reader where to return
- optional and debug commands live in the reference section
- success output appears only after the step that actually guarantees it
- robot/control-machine command blocks are clearly labeled

