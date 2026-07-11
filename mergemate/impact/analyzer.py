"""
ImpactAnalyzer: coordinates the full impact analysis pipeline.
"""
from __future__ import annotations

from mergemate.domain.models import (
    GitChangeSet,
    MavenProject,
    ImpactAnalysis,
    ModuleImpact,
    MavenCommand,
    ValidationPlan,
)
from mergemate.impact.module_graph import ModuleGraph
from mergemate.impact.file_mapper import map_changeset_to_modules, is_root_pom_change
from mergemate.impact.risk import evaluate_risks
from mergemate.maven.wrapper import get_effective_maven_argv
from mergemate.config.loader import MergeMateConfig


class ImpactAnalyzer:
    def __init__(self, config: MergeMateConfig | None = None):
        self.config = config or MergeMateConfig()

    def analyze(
        self,
        changeset: GitChangeSet,
        project: MavenProject,
        project_dir: str,
    ) -> ImpactAnalysis:
        """
        Full impact analysis pipeline:

        1. Map changed files -> modules
        2. Build module graph
        3. Compute transitive dependents
        4. Evaluate risk rules
        5. Decide strategy (full vs incremental)
        6. Build ImpactAnalysis result

        Module labels:
        - "changed": module that directly has changed files
        - "dependent": module that transitively depends on a changed module
        - "dependency": module added by -am (upstream dep of changed/dependent)
        """
        # 1. Map changed files to modules
        module_file_map = map_changeset_to_modules(changeset.changed_files, project)

        # Determine directly changed module IDs
        changed_module_ids: set[str] = set()
        for artifact_id, files in module_file_map.items():
            if artifact_id and files:  # exclude empty key (unmapped files)
                changed_module_ids.add(artifact_id)

        # 2. Build module graph
        graph = ModuleGraph(project)

        # 3. Compute transitive dependents
        max_depth = self.config.impact_max_depth
        dependent_module_ids = graph.transitive_dependents(
            changed_module_ids, max_depth=max_depth
        )

        # 4. Compute impact ratio
        total_modules = len(project.modules)
        affected_count = len(changed_module_ids) + len(dependent_module_ids)
        impact_ratio = affected_count / total_modules if total_modules > 0 else 0.0

        # 5. Evaluate risk rules
        risk_level, risk_reasons, full_build_recommended = evaluate_risks(
            changeset, project, module_file_map, self.config, impact_ratio
        )

        # 6. Determine strategy
        if full_build_recommended or not changed_module_ids:
            strategy = "full"
            strategy_reason = (
                "Full build recommended by risk rules"
                if full_build_recommended
                else "No module changes detected"
            )
        else:
            strategy = "incremental"
            strategy_reason = f"{len(changed_module_ids)} changed module(s), {len(dependent_module_ids)} dependent(s)"

        # 7. Build affected modules list
        affected_modules: list[ModuleImpact] = []

        if strategy == "full":
            # All modules are "changed" in a full build
            for artifact_id in sorted(project.modules.keys()):
                affected_modules.append(ModuleImpact(
                    artifact_id=artifact_id,
                    label="changed",
                    reason="Full build: all modules included",
                ))
        else:
            # Incremental: changed + dependents + their transitive deps

            # transitive dependencies of (changed + dependents) for -am
            all_primary = changed_module_ids | dependent_module_ids
            dep_module_ids = graph.transitive_dependencies(all_primary, max_depth=max_depth)
            # Remove those already in primary set
            dep_module_ids -= all_primary

            for artifact_id in sorted(changed_module_ids):
                affected_modules.append(ModuleImpact(
                    artifact_id=artifact_id,
                    label="changed",
                    reason="Has changed files",
                ))
            for artifact_id in sorted(dependent_module_ids):
                affected_modules.append(ModuleImpact(
                    artifact_id=artifact_id,
                    label="dependent",
                    reason="Transitively depends on a changed module",
                ))
            for artifact_id in sorted(dep_module_ids):
                affected_modules.append(ModuleImpact(
                    artifact_id=artifact_id,
                    label="dependency",
                    reason="Upstream dependency (added by -am)",
                ))

        return ImpactAnalysis(
            strategy=strategy,
            strategy_reason=strategy_reason,
            changed_modules=sorted(changed_module_ids),
            affected_modules=affected_modules,
            risk_level=risk_level,
            risk_reasons=risk_reasons,
            full_build_recommended=full_build_recommended,
        )

    def build_validation_plan(
        self,
        impact: ImpactAnalysis,
        project: MavenProject,
        project_dir: str,
        goal: str = "test",   # "test", "compile", "verify"
        skip_tests: bool = False,
    ) -> ValidationPlan:
        """
        Build a ValidationPlan from ImpactAnalysis.

        For incremental:
          ./mvnw -pl :mod-a,:mod-b -am <goal>

        For full:
          ./mvnw <goal>

        For analyze-only (goal=None):
          maven_command = None

        Returns ValidationPlan with the MavenCommand argv list.
        """
        if goal is None:
            return ValidationPlan(
                impact=impact,
                maven_command=None,
                profile="analyze",
            )

        maven_args: list[str] = []

        if impact.strategy == "incremental":
            # Collect changed + dependent modules for -pl
            primary_ids = [
                m.artifact_id
                for m in impact.affected_modules
                if m.label in ("changed", "dependent")
            ]
            if primary_ids:
                pl_arg = ",".join(f":{aid}" for aid in primary_ids)
                maven_args += ["-pl", pl_arg, "-am"]

        maven_args.append(goal)

        if goal == "compile" or skip_tests:
            maven_args.append("-DskipTests")

        argv = get_effective_maven_argv(project_dir, maven_args)
        display = " ".join(argv)

        maven_cmd = MavenCommand(
            argv=argv,
            display_command=display,
            goal=goal,
        )

        return ValidationPlan(
            impact=impact,
            maven_command=maven_cmd,
            profile=goal,
        )
