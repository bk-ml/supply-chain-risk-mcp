import asyncio
import os

from dotenv import load_dotenv
load_dotenv()

from orchestration.llm_backend import GeminiBackend
from orchestration.triage_agent import TriageAgent
from orchestration.research_agent import ResearchAgent
from orchestration.synthesis_agent import SynthesisAgent
from orchestration.orchestrator import Orchestrator
from orchestration.schemas import PRDiffInput

from evals.cases import CASES

DRY_RUN_IDS = {
    "gpl_dependency_into_mit_project",
    "lockfile_hash_only_churn",
    "whitespace_only_manifest_change",
}


async def main():
    backend = GeminiBackend(api_key=os.environ["GEMINI_API_KEY"])
    orchestrator = Orchestrator(
        triage_agent=TriageAgent(backend),
        research_agent=ResearchAgent(),
        synthesis_agent=SynthesisAgent(backend),
    )

    for case in CASES:
        if case.id not in DRY_RUN_IDS:
            continue

        print(f"\n{'='*60}\n{case.id}: {case.description}\n{'='*60}")

        pr_diff = PRDiffInput(
            repo_owner=case.repo_owner, repo_name=case.repo_name,
            diff_text=case.diff_text, changed_files=case.changed_files,
            project_license=case.project_license,
        )
        output = await orchestrator.run(pr_diff)
        print(output.model_dump_json(indent=2))
        print(f"\n[expected] unable_to_assess={case.expect_unable_to_assess}, "
              f"min_affected_packages={case.expect_min_affected_packages}")


asyncio.run(main())