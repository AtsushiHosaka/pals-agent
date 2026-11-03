import Mathlib

/-!
Export every Prop-valued `theorem` constant of the pinned Mathlib environment to JSONL.

The exporter reads the compiled environment, never Mathlib's source text, so generated copies and
attribute data are visible. `type_hash` is only a prefilter: identity must be confirmed by Lean.

Configuration comes from the environment: `PALS_INDEX_OUT_DIR` (required), `PALS_INDEX_SHARDS`
(default 12) and `PALS_INDEX_LIMIT` (default: no limit).
-/

open Lean Meta

namespace PalsMathlibIndex

structure Shared where
  simpLemmas : SimpTheorems
  normCast : NameSet
  pushCast : SimpTheorems
  extLemmas : NameSet
  additiveSources : NameMap Name
  dualLinked : NameSet
  crossRefs : NameMap (Array String)

private def nameJson (n : Name) : Json := Json.str n.toString

private def isInstanceLike (env : Environment) (n : Name) : Bool :=
  Meta.isInstanceCore env n

/-- Constants of `e` without instances: those describe the ambient structure, not the statement. -/
private def statementConstants (env : Environment) (e : Expr) : Array Name :=
  e.getUsedConstants.filter fun n => !isInstanceLike env n

private def conclusionHead (e : Expr) : Option Name :=
  e.getAppFn.constName?

/-- Binder summary of a statement, read through `forallTelescope` without reducing definitions. -/
private def statementShape (type : Expr) : MetaM Json := do
  forallTelescope type fun xs conclusion => do
    let mut explicitArgs : Nat := 0
    let mut implicitArgs : Nat := 0
    let mut instArgs : Nat := 0
    let mut propArgs : Nat := 0
    let mut hypothesisConstants : Array Name := #[]
    let env ← getEnv
    for x in xs do
      let decl ← x.fvarId!.getDecl
      match decl.binderInfo with
      | .instImplicit => instArgs := instArgs + 1
      | .default => explicitArgs := explicitArgs + 1
      | _ => implicitArgs := implicitArgs + 1
      if !decl.binderInfo.isInstImplicit then
        if ← isProp decl.type then
          propArgs := propArgs + 1
          hypothesisConstants := hypothesisConstants ++ statementConstants env decl.type
    let instTypes ← xs.filterM fun x => return (← x.fvarId!.getDecl).binderInfo.isInstImplicit
    let classes ← instTypes.filterMapM fun x => do
      return (← x.fvarId!.getType).getAppFn.constName?
    return Json.mkObj [
      ("explicit_args", toJson explicitArgs),
      ("implicit_args", toJson implicitArgs),
      ("inst_args", toJson instArgs),
      ("prop_args", toJson propArgs),
      ("conclusion_head", match conclusionHead conclusion with
        | some head => nameJson head
        | none => Json.null),
      ("conclusion_constants",
        toJson ((statementConstants env conclusion).map (·.toString))),
      ("hypothesis_constants",
        toJson ((hypothesisConstants.toList.eraseDups.toArray).map (·.toString))),
      ("classes", toJson (classes.map (·.toString)))]

/-- Theorems used directly by a proof body. The Python side aggregates them into usage counts. -/
private def proofTheorems (env : Environment) (value : Expr) : Array String :=
  (value.getUsedConstants.filter fun n =>
    match env.find? n with
    | some (.thmInfo _) => true
    | _ => false).map (·.toString)

private def declaration (shared : Shared) (name : Name) (type value : Expr) : MetaM Json := do
  let env ← getEnv
  let moduleName := match env.getModuleIdxFor? name with
    | some idx => env.header.moduleNames[idx.toNat]!
    | none => Name.anonymous
  let shape ← withCurrHeartbeats <| statementShape type
  let pretty ← withCurrHeartbeats do
    try
      withOptions (fun o => (pp.proofs.set o false)) do
        return toString (← ppExpr type)
    catch _ => return ""
  let doc ← findDocString? env name
  let ranges ← findDeclarationRanges? name
  let declRange := ranges.map (·.range.pos)
  return Json.mkObj [
    ("name", nameJson name),
    ("module", nameJson moduleName),
    ("line", match declRange with | some p => toJson p.line | none => Json.null),
    ("column", match declRange with | some p => toJson p.column | none => Json.null),
    ("type", pretty),
    ("type_hash", toString type.hash),
    ("doc", match doc with | some d => Json.str d | none => Json.null),
    ("shape", shape),
    ("attrs", Json.mkObj [
      ("simp", shared.simpLemmas.isLemma (.decl name)),
      ("norm_cast", shared.normCast.contains name),
      ("push_cast", shared.pushCast.isLemma (.decl name)),
      ("ext", shared.extLemmas.contains name),
      ("instance", isInstanceLike env name),
      ("to_dual_linked", shared.dualLinked.contains name),
      ("deprecated", Linter.isDeprecated env name),
      ("private", isPrivateName name),
      ("completion_blocked", !allowCompletion env name),
      ("internal", ← isAutoDeclOrPrivate_Internal name)]),
    ("additive_source", match shared.additiveSources.find? name with
      | some source => nameJson source
      | none => Json.null),
    ("cross_refs", match shared.crossRefs.find? name with
      | some refs => toJson refs
      | none => toJson (#[] : Array String)),
    ("proof_constants", toJson (proofTheorems env value))]

private def writeShard (shared : Shared) (path : System.FilePath)
    (items : Array (Name × ConstantInfo)) : CoreM Nat := do
  let handle ← IO.FS.Handle.mk path .write
  let mut written := 0
  for (name, info) in items do
    let value := match info with
      | .thmInfo thm => thm.value
      | _ => mkConst `unreachable
    let line ← (declaration shared name info.type value).run'
    handle.putStrLn line.compress
    written := written + 1
    if written % 200 == 0 then
      Core.checkSystem "mathlib index export"
  return written

def run : CoreM Unit := do
  let outDir := System.FilePath.mk ((← IO.getEnv "PALS_INDEX_OUT_DIR").getD "")
  if outDir.toString.isEmpty then
    throwError "PALS_INDEX_OUT_DIR is required"
  let shards := ((← IO.getEnv "PALS_INDEX_SHARDS").bind String.toNat?).getD 12
  let limit := (← IO.getEnv "PALS_INDEX_LIMIT").bind String.toNat?
  IO.FS.createDirAll outDir
  let env ← getEnv
  let all := env.constants.fold (init := (#[] : Array (Name × ConstantInfo))) fun acc name info =>
    if info matches .thmInfo _ then acc.push (name, info) else acc
  let sorted := all.qsort (fun a b => Name.lt a.1 b.1)
  let selected := match limit with
    | some n => sorted.extract 0 n
    | none => sorted
  IO.eprintln s!"theorem constants: {all.size}; exporting {selected.size}"
  let additiveMap :=
    (SimplePersistentEnvExtension.getState Mathlib.Tactic.ToAdditive.translations env).get
  let additiveSources := additiveMap.foldl
    (fun acc source info => acc.insert info.translation source) ({} : NameMap Name)
  let dualMap := (SimplePersistentEnvExtension.getState Mathlib.Tactic.ToDual.translations env).get
  let dualLinked := dualMap.foldl
    (fun acc source info => (acc.insert source).insert info.translation) ({} : NameSet)
  let mut crossRefs : NameMap (Array String) := {}
  for moduleTags in SimplePersistentEnvExtension.getState Mathlib.CrossRef.tagExt env do
    for tag in moduleTags do
      let label := match tag.database with
        | .stacks => "stacks"
        | .kerodon => "kerodon"
        | .wikidata => "wikidata"
      crossRefs := crossRefs.insert tag.declName
        (((crossRefs.find? tag.declName).getD #[]).push s!"{label}:{tag.tag}")
  let normCastNames := [NormCast.normCastExt.up, NormCast.normCastExt.down,
      NormCast.normCastExt.squash].foldl (init := ({} : NameSet)) fun acc ext =>
    (ext.getState env).lemmaNames.fold (init := acc) fun acc origin =>
      match origin with
      | .decl n .. => acc.insert n
      | _ => acc
  let extState := Ext.extExtension.getState env
  let extLemmas := extState.tree.values.foldl (init := ({} : NameSet)) fun acc thm =>
    if extState.erased.contains thm.declName then acc else acc.insert thm.declName
  let shared : Shared := {
    extLemmas
    simpLemmas := simpExtension.getState env
    normCast := normCastNames
    pushCast := NormCast.pushCastExt.getState env
    additiveSources
    dualLinked
    crossRefs
  }
  let chunk := selected.size / shards + 1
  let ctx ← read
  let state ← get
  let tasks ← (List.range shards).mapM fun i => do
    let items := selected.extract (i * chunk) ((i + 1) * chunk)
    let path := outDir / s!"shard-{i}.jsonl"
    IO.asTask (prio := .dedicated) <|
      EIO.toIO (fun _ => IO.userError "export failed")
        ((writeShard shared path items).run' ctx state)
  let mut total := 0
  for task in tasks do
    total := total + (← IO.ofExcept (← IO.wait task))
  IO.FS.writeFile (outDir / "export-summary.json") <| (Json.mkObj [
    ("theorem_constants", all.size),
    ("exported", total),
    ("lean_version", Lean.versionString)]).compress
  IO.eprintln s!"wrote {total} records"

end PalsMathlibIndex

set_option maxHeartbeats 0 in
#eval PalsMathlibIndex.run
