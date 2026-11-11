import Lean
open Lean Elab

/-- A long-lived elaborator: imports Mathlib once, then elaborates one command file per request.
Protocol (stdin/stdout lines): request `<path>`; the worker prints every message, then `PALS_DONE`.
Each request starts from the same imported environment, so requests cannot affect each other. -/
unsafe def run : IO Unit := do
  enableInitializersExecution
  initSearchPath (← findSysroot)
  let env ← importModules #[{ module := `Mathlib }] {} 0 (loadExts := true)
  let stdin ← IO.getStdin
  let stdout ← IO.getStdout
  stdout.putStrLn "PALS_READY"
  stdout.flush
  repeat
    let line ← stdin.getLine
    if line.isEmpty then break
    let path := line.trimAscii.toString
    let src ← IO.FS.readFile path
    let inputCtx := Parser.mkInputContext src path
    let cmdState := Command.mkState env {} {}
    let s ← IO.processCommands inputCtx {} cmdState
    for msg in s.commandState.messages.toList do
      stdout.putStr (← msg.toString)
    stdout.putStrLn "PALS_DONE"
    stdout.flush

@[implemented_by run] opaque mainSafe : IO Unit

def main : IO Unit := mainSafe
