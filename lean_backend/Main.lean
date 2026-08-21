-- Main.lean — lean-checker-repl v0.2.1 spike Stage 1
-- REPL loop reading one JSON request per line from stdin, writing one
-- JSON response per line to stdout. See lakefile.lean for full context.
--
-- Protocol (Stage 1)
--   Request  (per line):  { "expression": "<string>" }
--   Response (VALID/INVALID):
--     { "verdict": "VALID", "checker_version": "..." }
--   Response (UNDECIDED):
--     { "verdict": "UNDECIDED", "reason_code": "<code>",
--       "detail": "<string>", "checker_version": "..." }
--   Sentinel line "__QUIT__" ends the loop cleanly.
--
-- Truth table (Stage 1) matches rei_checker/backend.py::MockBackend
-- so Stage 1 integration tests can compare backends. Stage 2 replaces
-- this with real Lean elaboration (see ../docs/V02_PROTOCOL.md).

import Lean.Data.Json
import Lean.Data.Json.Parser
import Lean.Data.Json.Printer

open Lean

def checkerVersion : String := "lean-checker-repl/0.2.1a1+spike-2026-08-22"

/-- Hardcoded truth table (Stage 1). Mirrors MockBackend semantics. -/
def truthTable (expr : String) : Option Bool :=
  match expr with
  | "1 + 1 = 2"          => some true
  | "∀ n : ℕ, n + 0 = n" => some true
  | "True"               => some true
  | "1 + 1 = 3"          => some false
  | "∀ n : ℕ, n + 1 = n" => some false
  | "False"              => some false
  | _                    => none

/-- Reason-code triggers for exercising each UNDECIDED code path.
    Kept identical to MockBackend._REASON_TRIGGERS. -/
def reasonTrigger (expr : String) : Option (String × String) :=
  match expr with
  | "<timeout-test>" => some ("TIMEOUT",            "mock trigger for TIMEOUT")
  | "<syntax-test>"  => some ("UNSUPPORTED_SYNTAX", "mock trigger for UNSUPPORTED_SYNTAX")
  | "<axiom-test>"   => some ("MISSING_AXIOM",      "mock trigger for MISSING_AXIOM")
  | "<depth-test>"   => some ("DEPTH_LIMIT",        "mock trigger for DEPTH_LIMIT")
  | _                => none

/-- Build a VerifyResult-shaped JSON object. -/
def mkVerdictJson (verdict : String) (reasonCode : Option String) (detail : Option String)
    : Json :=
  let base : List (String × Json) := [
    ("verdict",         Json.str verdict),
    ("checker_version", Json.str checkerVersion)
  ]
  let withReason := match reasonCode with
    | some rc => base ++ [("reason_code", Json.str rc)]
    | none    => base
  let withDetail := match detail with
    | some d => withReason ++ [("detail", Json.str d)]
    | none   => withReason
  Json.mkObj withDetail

/-- Judge one expression through the Stage 1 hardcoded table. -/
def judge (expression : String) : Json :=
  let trimmed := expression.trim
  if trimmed.isEmpty then
    mkVerdictJson "UNDECIDED" (some "PARSE_FAILURE")
                  (some "expression is empty or whitespace-only")
  else
    match reasonTrigger trimmed with
    | some (code, detail) =>
        mkVerdictJson "UNDECIDED" (some code) (some detail)
    | none =>
        match truthTable trimmed with
        | some true  => mkVerdictJson "VALID" none none
        | some false => mkVerdictJson "INVALID" none none
        | none       =>
            mkVerdictJson "UNDECIDED" (some "OUT_OF_SCOPE")
                          (some "Stage 1 harness has no rule for this expression")

/-- Turn a parsed JSON request into a JSON response.
    Malformed requests get an UNDECIDED/PARSE_FAILURE with the reason
    explained in `detail` — never crash the REPL. -/
def processRequest (j : Json) : Json :=
  match j.getObjValAs? String "expression" with
  | .ok expression => judge expression
  | .error msg     =>
      mkVerdictJson "UNDECIDED" (some "PARSE_FAILURE")
                    (some s!"missing 'expression' field: {msg}")

/-- One iteration: read one line, parse, respond. Returns true iff we
    should keep looping (false = clean shutdown via EOF or __QUIT__). -/
partial def handleOneLine : IO Bool := do
  let stdin ← IO.getStdin
  let line ← stdin.getLine
  -- Empty return-string means EOF (Lean's IO.FS.Stream.getLine convention).
  if line.isEmpty then
    return false
  let trimmed := line.trim
  if trimmed.isEmpty then
    -- Blank line: ignore, keep looping.
    return true
  if trimmed == "__QUIT__" then
    return false
  match Json.parse trimmed with
  | .error msg =>
      let resp := mkVerdictJson "UNDECIDED" (some "PARSE_FAILURE")
                                (some s!"invalid JSON: {msg}")
      IO.println (resp.compress)
  | .ok req =>
      let resp := processRequest req
      IO.println (resp.compress)
  -- Flush after every response so the caller sees output immediately.
  (← IO.getStdout).flush
  return true

/-- Main REPL loop. Blocks until stdin closes or __QUIT__ arrives. -/
partial def replLoop : IO Unit := do
  let cont ← handleOneLine
  if cont then replLoop

def main : IO Unit := do
  -- Line-buffered stdout so downstream sees each response promptly.
  -- Lean's IO.println already writes \n; the flush inside handleOneLine
  -- covers Windows console + pipe buffering both.
  replLoop
