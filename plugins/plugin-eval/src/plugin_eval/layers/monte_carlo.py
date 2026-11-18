"""Layer 3: Monte Carlo simulation — statistical reliability testing via repeated runs."""

from __future__ import annotations

import asyncio
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from plugin_eval.layers._sdk import collect_sdk_output, usage_total_tokens
from plugin_eval.models import LayerResult
from plugin_eval.parser import ParsedSkill, parse_skill
from plugin_eval.stats import (
    bootstrap_ci,
    clopper_pearson_ci,
    coefficient_of_variation,
    wilson_score_ci,
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SimResult:
    """Result of a single simulation run."""

    activated: bool
    quality_score: float
    tokens: int
    duration_ms: int
    errored: bool = False
    prompt: str = ""
    model: str | None = None


@dataclass
class MonteCarloConfig:
    """Configuration for Monte Carlo simulation runs."""

    n_runs: int = 50
    concurrency: int = 4
    seed: int = 42
    progress_callback: Callable[[int, int], None] | None = None


# ---------------------------------------------------------------------------
# Single simulation runner
# ---------------------------------------------------------------------------


def _simresult_from_messages(messages: list, prompt: str, duration_ms: int) -> SimResult:
    """Build a SimResult from SDK messages (assistant text => activation + quality)."""
    output = collect_sdk_output(messages)
    tokens = usage_total_tokens(output.usage)
    # An errored run carries diagnostic text, not skill output, so it must not
    # register as activation. Counting it inflates the activation rate and puts
    # this metric at odds with output consistency and token efficiency (both
    # already drop errored runs) and with the exception path below, which
    # reports activated=False for a run that failed before producing anything.
    raw = "" if output.errored else (output.text.strip() or (output.result or "").strip())
    activated = bool(raw)
    quality_score = min(1.0, len(raw) / 500) if activated else 0.0
    return SimResult(
        activated=activated,
        quality_score=quality_score,
        tokens=tokens,
        duration_ms=duration_ms,
        errored=output.errored,
        prompt=prompt,
        model=output.model,
    )


async def run_simulation(skill_content: str, prompt: str) -> SimResult:
    """Run a single simulation via Agent SDK. Returns SimResult. On error, errored=True."""
    try:
        import time

        from claude_agent_sdk import (  # type: ignore[import-untyped]
            ClaudeAgentOptions,
            query,
        )

        full_prompt = (
            f"You are evaluating a skill. Apply the skill if appropriate.\n\n"
            f"{skill_content}\n\n{prompt}"
        )
        start = time.monotonic()
        messages = [
            message
            async for message in query(
                prompt=full_prompt,
                options=ClaudeAgentOptions(allowed_tools=[]),
            )
        ]
        duration_ms = int((time.monotonic() - start) * 1000)
        return _simresult_from_messages(messages, prompt, duration_ms)
    except Exception:  # noqa: BLE001 — a failed run is recorded as errored, not fatal
        return SimResult(
            activated=False,
            quality_score=0.0,
            tokens=0,
            duration_ms=0,
            errored=True,
            prompt=prompt,
        )


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class MonteCarloAnalyzer:
    """Statistical reliability testing via repeated simulated runs."""

    def __init__(self, config: MonteCarloConfig) -> None:
        self.config = config
        self._sem = asyncio.Semaphore(config.concurrency)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze_skill(self, skill_or_dir: Path | ParsedSkill) -> LayerResult:
        """Generate prompts, run N simulations, compute statistics, return LayerResult."""
        skill = skill_or_dir if isinstance(skill_or_dir, ParsedSkill) else parse_skill(skill_or_dir)
        skill_content = skill.raw_content

        model_usage: dict[str, int] = {}
        prompts = await self._generate_prompts(
            skill.name, skill.description, usage_sink=model_usage
        )

        # Repeat prompts to reach n_runs
        repeated: list[str] = []
        while len(repeated) < self.config.n_runs:
            repeated.extend(prompts)
        prompts_to_run = repeated[: self.config.n_runs]

        results = await self._run_all(skill_content, prompts_to_run)
        stats = self._compute_statistics(results)

        # Aggregate per-sim token usage by the model the SDK actually reported.
        for r in results:
            if r.model and r.tokens:
                model_usage[r.model] = model_usage.get(r.model, 0) + r.tokens

        triggering = stats["triggering"]
        output_consistency = stats["output_consistency"]
        failure_rate = stats["failure_rate"]
        token_efficiency = stats["token_efficiency"]

        activation_rate = triggering.get("activation_rate", 0.0)
        cv = output_consistency.get("cv", 1.0)
        p_fail = failure_rate.get("p_fail", 1.0)
        efficiency_norm = token_efficiency.get("efficiency_norm", 0.0)

        # Composite: 0.40 * trigger_reliability + 0.30 * (1-cv) + 0.20 * (1-p_fail) + 0.10 * efficiency_norm
        score = (
            0.40 * activation_rate
            + 0.30 * (1.0 - min(1.0, cv))
            + 0.20 * (1.0 - p_fail)
            + 0.10 * efficiency_norm
        )
        score = max(0.0, min(1.0, score))

        sub_scores: dict = {
            "triggering": triggering,
            "output_consistency": output_consistency,
            "failure_rate": failure_rate,
            "token_efficiency": token_efficiency,
        }

        metadata: dict = {
            "n_runs": len(results),
            "n_activated": sum(1 for r in results if r.activated),
            "n_errored": sum(1 for r in results if r.errored),
            "model_usage": model_usage,
        }

        return LayerResult(
            layer="monte_carlo",
            score=score,
            sub_scores=sub_scores,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Prompt generation
    # ------------------------------------------------------------------

    async def _generate_prompts(
        self, name: str, description: str, usage_sink: dict[str, int] | None = None
    ) -> list[str]:
        """Use Haiku to generate 15 varied prompts. Falls back to basic variants."""
        try:
            from plugin_eval.layers.judge import query_llm

            model = "claude-haiku-4-5-20251001"
            system = (
                "You are generating test prompts for a Claude Code skill. "
                "Respond ONLY with a JSON array of strings — no explanation, no markdown fences."
            )
            prompt = (
                f"Generate 15 varied user prompts that would trigger this skill:\n\n"
                f"Name: {name}\n"
                f"Description: {description}\n\n"
                f'Return a JSON array of 15 strings. Example: ["prompt 1", "prompt 2", ...]'
           …37981 tokens truncated…ze = 383843, upload-time = "2025-11-30T20:23:14.638Z" },
    { url = "https://files.pythonhosted.org/packages/82/86/d5f2e04f2aa6247c613da0c1dd87fcd08fa17107e858193566048a1e2f0a/rpds_py-0.30.0-cp313-cp313t-manylinux_2_31_riscv64.whl", hash = "sha256:eb2c4071ab598733724c08221091e8d80e89064cd472819285a9ab0f24bcedb9", size = 396507, upload-time = "2025-11-30T20:23:16.105Z" },
    { url = "https://files.pythonhosted.org/packages/4b/9a/453255d2f769fe44e07ea9785c8347edaf867f7026872e76c1ad9f7bed92/rpds_py-0.30.0-cp313-cp313t-manylinux_2_5_i686.manylinux1_i686.whl", hash = "sha256:6bdfdb946967d816e6adf9a3d8201bfad269c67efe6cefd7093ef959683c8de0", size = 414949, upload-time = "2025-11-30T20:23:17.539Z" },
    { url = "https://files.pythonhosted.org/packages/a3/31/622a86cdc0c45d6df0e9ccb6becdba5074735e7033c20e401a6d9d0e2ca0/rpds_py-0.30.0-cp313-cp313t-musllinux_1_2_aarch64.whl", hash = "sha256:c77afbd5f5250bf27bf516c7c4a016813eb2d3e116139aed0096940c5982da94", size = 565790, upload-time = "2025-11-30T20:23:19.029Z" },
    { url = "https://files.pythonhosted.org/packages/1c/5d/15bbf0fb4a3f58a3b1c67855ec1efcc4ceaef4e86644665fff03e1b66d8d/rpds_py-0.30.0-cp313-cp313t-musllinux_1_2_i686.whl", hash = "sha256:61046904275472a76c8c90c9ccee9013d70a6d0f73eecefd38c1ae7c39045a08", size = 590217, upload-time = "2025-11-30T20:23:20.885Z" },
    { url = "https://files.pythonhosted.org/packages/6d/61/21b8c41f68e60c8cc3b2e25644f0e3681926020f11d06ab0b78e3c6bbff1/rpds_py-0.30.0-cp313-cp313t-musllinux_1_2_x86_64.whl", hash = "sha256:4c5f36a861bc4b7da6516dbdf302c55313afa09b81931e8280361a4f6c9a2d27", size = 555806, upload-time = "2025-11-30T20:23:22.488Z" },
    { url = "https://files.pythonhosted.org/packages/f9/39/7e067bb06c31de48de3eb200f9fc7c58982a4d3db44b07e73963e10d3be9/rpds_py-0.30.0-cp313-cp313t-win32.whl", hash = "sha256:3d4a69de7a3e50ffc214ae16d79d8fbb0922972da0356dcf4d0fdca2878559c6", size = 211341, upload-time = "2025-11-30T20:23:24.449Z" },
    { url = "https://files.pythonhosted.org/packages/0a/4d/222ef0b46443cf4cf46764d9c630f3fe4abaa7245be9417e56e9f52b8f65/rpds_py-0.30.0-cp313-cp313t-win_amd64.whl", hash = "sha256:f14fc5df50a716f7ece6a80b6c78bb35ea2ca47c499e422aa4463455dd96d56d", size = 225768, upload-time = "2025-11-30T20:23:25.908Z" },
    { url = "https://files.pythonhosted.org/packages/86/81/dad16382ebbd3d0e0328776d8fd7ca94220e4fa0798d1dc5e7da48cb3201/rpds_py-0.30.0-cp314-cp314-macosx_10_12_x86_64.whl", hash = "sha256:68f19c879420aa08f61203801423f6cd5ac5f0ac4ac82a2368a9fcd6a9a075e0", size = 362099, upload-time = "2025-11-30T20:23:27.316Z" },
    { url = "https://files.pythonhosted.org/packages/2b/60/19f7884db5d5603edf3c6bce35408f45ad3e97e10007df0e17dd57af18f8/rpds_py-0.30.0-cp314-cp314-macosx_11_0_arm64.whl", hash = "sha256:ec7c4490c672c1a0389d319b3a9cfcd098dcdc4783991553c332a15acf7249be", size = 353192, upload-time = "2025-11-30T20:23:29.151Z" },
    { url = "https://files.pythonhosted.org/packages/bf/c4/76eb0e1e72d1a9c4703c69607cec123c29028bff28ce41588792417098ac/rpds_py-0.30.0-cp314-cp314-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", hash = "sha256:f251c812357a3fed308d684a5079ddfb9d933860fc6de89f2b7ab00da481e65f", size = 384080, upload-time = "2025-11-30T20:23:30.785Z" },
    { url = "https://files.pythonhosted.org/packages/72/87/87ea665e92f3298d1b26d78814721dc39ed8d2c74b86e83348d6b48a6f31/rpds_py-0.30.0-cp314-cp314-manylinux_2_17_armv7l.manylinux2014_armv7l.whl", hash = "sha256:ac98b175585ecf4c0348fd7b29c3864bda53b805c773cbf7bfdaffc8070c976f", size = 394841, upload-time = "2025-11-30T20:23:32.209Z" },
    { url = "https://files.pythonhosted.org/packages/77/ad/7783a89ca0587c15dcbf139b4a8364a872a25f861bdb88ed99f9b0dec985/rpds_py-0.30.0-cp314-cp314-manylinux_2_17_ppc64le.manylinux2014_ppc64le.whl", hash = "sha256:3e62880792319dbeb7eb866547f2e35973289e7d5696c6e295476448f5b63c87", size = 516670, upload-time = "2025-11-30T20:23:33.742Z" },
    { url = "https://files.pythonhosted.org/packages/5b/3c/2882bdac942bd2172f3da574eab16f309ae10a3925644e969536553cb4ee/rpds_py-0.30.0-cp314-cp314-manylinux_2_17_s390x.manylinux2014_s390x.whl", hash = "sha256:4e7fc54e0900ab35d041b0601431b0a0eb495f0851a0639b6ef90f7741b39a18", size = 408005, upload-time = "2025-11-30T20:23:35.253Z" },
    { url = "https://files.pythonhosted.org/packages/ce/81/9a91c0111ce1758c92516a3e44776920b579d9a7c09b2b06b642d4de3f0f/rpds_py-0.30.0-cp314-cp314-manylinux_2_17_x86_64.manylinux2014_x86_64.whl", hash = "sha256:47e77dc9822d3ad616c3d5759ea5631a75e5809d5a28707744ef79d7a1bcfcad", size = 382112, upload-time = "2025-11-30T20:23:36.842Z" },
    { url = "https://files.pythonhosted.org/packages/cf/8e/1da49d4a107027e5fbc64daeab96a0706361a2918da10cb41769244b805d/rpds_py-0.30.0-cp314-cp314-manylinux_2_31_riscv64.whl", hash = "sha256:b4dc1a6ff022ff85ecafef7979a2c6eb423430e05f1165d6688234e62ba99a07", size = 399049, upload-time = "2025-11-30T20:23:38.343Z" },
    { url = "https://files.pythonhosted.org/packages/df/5a/7ee239b1aa48a127570ec03becbb29c9d5a9eb092febbd1699d567cae859/rpds_py-0.30.0-cp314-cp314-manylinux_2_5_i686.manylinux1_i686.whl", hash = "sha256:4559c972db3a360808309e06a74628b95eaccbf961c335c8fe0d590cf587456f", size = 415661, upload-time = "2025-11-30T20:23:40.263Z" },
    { url = "https://files.pythonhosted.org/packages/70/ea/caa143cf6b772f823bc7929a45da1fa83569ee49b11d18d0ada7f5ee6fd6/rpds_py-0.30.0-cp314-cp314-musllinux_1_2_aarch64.whl", hash = "sha256:0ed177ed9bded28f8deb6ab40c183cd1192aa0de40c12f38be4d59cd33cb5c65", size = 565606, upload-time = "2025-11-30T20:23:42.186Z" },
    { url = "https://files.pythonhosted.org/packages/64/91/ac20ba2d69303f961ad8cf55bf7dbdb4763f627291ba3d0d7d67333cced9/rpds_py-0.30.0-cp314-cp314-musllinux_1_2_i686.whl", hash = "sha256:ad1fa8db769b76ea911cb4e10f049d80bf518c104f15b3edb2371cc65375c46f", size = 591126, upload-time = "2025-11-30T20:23:44.086Z" },
    { url = "https://files.pythonhosted.org/packages/21/20/7ff5f3c8b00c8a95f75985128c26ba44503fb35b8e0259d812766ea966c7/rpds_py-0.30.0-cp314-cp314-musllinux_1_2_x86_64.whl", hash = "sha256:46e83c697b1f1c72b50e5ee5adb4353eef7406fb3f2043d64c33f20ad1c2fc53", size = 553371, upload-time = "2025-11-30T20:23:46.004Z" },
    { url = "https://files.pythonhosted.org/packages/72/c7/81dadd7b27c8ee391c132a6b192111ca58d866577ce2d9b0ca157552cce0/rpds_py-0.30.0-cp314-cp314-win32.whl", hash = "sha256:ee454b2a007d57363c2dfd5b6ca4a5d7e2c518938f8ed3b706e37e5d470801ed", size = 215298, upload-time = "2025-11-30T20:23:47.696Z" },
    { url = "https://files.pythonhosted.org/packages/3e/d2/1aaac33287e8cfb07aab2e6b8ac1deca62f6f65411344f1433c55e6f3eb8/rpds_py-0.30.0-cp314-cp314-win_amd64.whl", hash = "sha256:95f0802447ac2d10bcc69f6dc28fe95fdf17940367b21d34e34c737870758950", size = 228604, upload-time = "2025-11-30T20:23:49.501Z" },
    { url = "https://files.pythonhosted.org/packages/e8/95/ab005315818cc519ad074cb7784dae60d939163108bd2b394e60dc7b5461/rpds_py-0.30.0-cp314-cp314-win_arm64.whl", hash = "sha256:613aa4771c99f03346e54c3f038e4cc574ac09a3ddfb0e8878487335e96dead6", size = 222391, upload-time = "2025-11-30T20:23:50.96Z" },
    { url = "https://files.pythonhosted.org/packages/9e/68/154fe0194d83b973cdedcdcc88947a2752411165930182ae41d983dcefa6/rpds_py-0.30.0-cp314-cp314t-macosx_10_12_x86_64.whl", hash = "sha256:7e6ecfcb62edfd632e56983964e6884851786443739dbfe3582947e87274f7cb", size = 364868, upload-time = "2025-11-30T20:23:52.494Z" },
    { url = "https://files.pythonhosted.org/packages/83/69/8bbc8b07ec854d92a8b75668c24d2abcb1719ebf890f5604c61c9369a16f/rpds_py-0.30.0-cp314-cp314t-macosx_11_0_arm64.whl", hash = "sha256:a1d0bc22a7cdc173fedebb73ef81e07faef93692b8c1ad3733b67e31e1b6e1b8", size = 353747, upload-time = "2025-11-30T20:23:54.036Z" },
    { url = "https://files.pythonhosted.org/packages/ab/00/ba2e50183dbd9abcce9497fa5149c62b4ff3e22d338a30d690f9af970561/rpds_py-0.30.0-cp314-cp314t-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", hash = "sha256:0d08f00679177226c4cb8c5265012eea897c8ca3b93f429e546600c971bcbae7", size = 383795, upload-time = "2025-11-30T20:23:55.556Z" },
    { url = "https://files.pythonhosted.org/packages/05/6f/86f0272b84926bcb0e4c972262f54223e8ecc556b3224d281e6598fc9268/rpds_py-0.30.0-cp314-cp314t-manylinux_2_17_armv7l.manylinux2014_armv7l.whl", hash = "sha256:5965af57d5848192c13534f90f9dd16464f3c37aaf166cc1da1cae1fd5a34898", size = 393330, upload-time = "2025-11-30T20:23:57.033Z" },
    { url = "https://files.pythonhosted.org/packages/cb/e9/0e02bb2e6dc63d212641da45df2b0bf29699d01715913e0d0f017ee29438/rpds_py-0.30.0-cp314-cp314t-manylinux_2_17_ppc64le.manylinux2014_ppc64le.whl", hash = "sha256:9a4e86e34e9ab6b667c27f3211ca48f73dba7cd3d90f8d5b11be56e5dbc3fb4e", size = 518194, upload-time = "2025-11-30T20:23:58.637Z" },
    { url = "https://files.pythonhosted.org/packages/ee/ca/be7bca14cf21513bdf9c0606aba17d1f389ea2b6987035eb4f62bd923f25/rpds_py-0.30.0-cp314-cp314t-manylinux_2_17_s390x.manylinux2014_s390x.whl", hash = "sha256:e5d3e6b26f2c785d65cc25ef1e5267ccbe1b069c5c21b8cc724efee290554419", size = 408340, upload-time = "2025-11-30T20:24:00.2Z" },
    { url = "https://files.pythonhosted.org/packages/c2/c7/736e00ebf39ed81d75544c0da6ef7b0998f8201b369acf842f9a90dc8fce/rpds_py-0.30.0-cp314-cp314t-manylinux_2_17_x86_64.manylinux2014_x86_64.whl", hash = "sha256:626a7433c34566535b6e56a1b39a7b17ba961e97ce3b80ec62e6f1312c025551", size = 383765, upload-time = "2025-11-30T20:24:01.759Z" },
    { url = "https://files.pythonhosted.org/packages/4a/3f/da50dfde9956aaf365c4adc9533b100008ed31aea635f2b8d7b627e25b49/rpds_py-0.30.0-cp314-cp314t-manylinux_2_31_riscv64.whl", hash = "sha256:acd7eb3f4471577b9b5a41baf02a978e8bdeb08b4b355273994f8b87032000a8", size = 396834, upload-time = "2025-11-30T20:24:03.687Z" },
    { url = "https://files.pythonhosted.org/packages/4e/00/34bcc2565b6020eab2623349efbdec810676ad571995911f1abdae62a3a0/rpds_py-0.30.0-cp314-cp314t-manylinux_2_5_i686.manylinux1_i686.whl", hash = "sha256:fe5fa731a1fa8a0a56b0977413f8cacac1768dad38d16b3a296712709476fbd5", size = 415470, upload-time = "2025-11-30T20:24:05.232Z" },
    { url = "https://files.pythonhosted.org/packages/8c/28/882e72b5b3e6f718d5453bd4d0d9cf8df36fddeb4ddbbab17869d5868616/rpds_py-0.30.0-cp314-cp314t-musllinux_1_2_aarch64.whl", hash = "sha256:74a3243a411126362712ee1524dfc90c650a503502f135d54d1b352bd01f2404", size = 565630, upload-time = "2025-11-30T20:24:06.878Z" },
    { url = "https://files.pythonhosted.org/packages/3b/97/04a65539c17692de5b85c6e293520fd01317fd878ea1995f0367d4532fb1/rpds_py-0.30.0-cp314-cp314t-musllinux_1_2_i686.whl", hash = "sha256:3e8eeb0544f2eb0d2581774be4c3410356eba189529a6b3e36bbbf9696175856", size = 591148, upload-time = "2025-11-30T20:24:08.445Z" },
    { url = "https://files.pythonhosted.org/packages/85/70/92482ccffb96f5441aab93e26c4d66489eb599efdcf96fad90c14bbfb976/rpds_py-0.30.0-cp314-cp314t-musllinux_1_2_x86_64.whl", hash = "sha256:dbd936cde57abfee19ab3213cf9c26be06d60750e60a8e4dd85d1ab12c8b1f40", size = 556030, upload-time = "2025-11-30T20:24:10.956Z" },
    { url = "https://files.pythonhosted.org/packages/20/53/7c7e784abfa500a2b6b583b147ee4bb5a2b3747a9166bab52fec4b5b5e7d/rpds_py-0.30.0-cp314-cp314t-win32.whl", hash = "sha256:dc824125c72246d924f7f796b4f63c1e9dc810c7d9e2355864b3c3a73d59ade0", size = 211570, upload-time = "2025-11-30T20:24:12.735Z" },
    { url = "https://files.pythonhosted.org/packages/d0/02/fa464cdfbe6b26e0600b62c528b72d8608f5cc49f96b8d6e38c95d60c676/rpds_py-0.30.0-cp314-cp314t-win_amd64.whl", hash = "sha256:27f4b0e92de5bfbc6f86e43959e6edd1425c33b5e69aab0984a72047f2bcf1e3", size = 226532, upload-time = "2025-11-30T20:24:14.634Z" },
]

[[package]]
name = "ruff"
version = "0.17.0"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/packages/e9/a7/70debb024dfacda67b8e560cc7511f52b34b9348a8cc8c1ec23036dcd51d/ruff-0.17.0.tar.gz", hash = "sha256:5cd03240d8208a557c2a9655a5cb07ebe36aa6bb35065f97d48c1f6adef5a322", size = 5320554, upload-time = "2026-10-09T19:47:29.248Z" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/bc/f8/ee5ab9da6089eae2a33e6008b01deb1eda19992c1c8e10661e98cee1640f/ruff-0.17.0-py3-none-linux_armv6l.whl", hash = "sha256:0e271826af9a20d18c6cfae8c51e82959167c24859686ddd3eb9a7f0842ce81e", size = 10148907, upload-time = "2026-10-09T19:46:38.695Z" },
    { url = "https://files.pythonhosted.org/packages/9f/d9/2f81fb5a9d580afbb11b1c8ff915233a11f2a1b27405d7991f183c5e1976/ruff-0.17.0-py3-none-macosx_10_12_x86_64.whl", hash = "sha256:5f0ca4a40f81403689c04f12966e22f44e329ae362072d8f1587b7bda87f603b", size = 10224208, upload-time = "2026-10-09T19:46:41.711Z" },
    { url = "https://files.pythonhosted.org/packages/a7/20/643f3c8f75594f937b2bf74801241c56a2e2b8e139d24dff8b66b28cdd7f/ruff-0.17.0-py3-none-macosx_11_0_arm64.whl", hash = "sha256:cbf7149e0927dc3295d5d64679a4765576eef71b00782b2ae969ef82274d6bb9", size = 9273324, upload-time = "2026-10-09T19:46:44.323Z" },
    { url = "https://files.pythonhosted.org/packages/ec/91/627700b233d367736cb274f1bd0b47d1f2b12f68878192812bd875adadc3/ruff-0.17.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", hash = "sha256:13ee90156522998c3037059d8f66885c8adeeaf7643bdce2caceee196ecd23e0", size = 9953190, upload-time = "2026-10-09T19:46:47.155Z" },
    { url = "https://files.pythonhosted.org/packages/cd/92/91f7b5ed39490f89d6cbf56e1f543c383667a725efa8e2c2dee0f01f5591/ruff-0.17.0-py3-none-manylinux_2_17_armv7l.manylinux2014_armv7l.whl", hash = "sha256:3d8e4a002a94cd9d0dc48b51dc69d807a172b5b9bf2b668e656424dc5b55ead1", size = 9961746, upload-time = "2026-10-09T19:46:50.098Z" },
    { url = "https://files.pythonhosted.org/packages/87/c5/7310f9fc63ce11ff6394edbd5e85433dfb0e14c9fbf6ccc97f1538491bc7/ruff-0.17.0-py3-none-manylinux_2_17_i686.manylinux2014_i686.whl", hash = "sha256:c0b8a60c06a218c337e1161638d34757f83449243e2db161483ddf948e53ad14", size = 10625483, upload-time = "2026-10-09T19:46:53.379Z" },
    { url = "https://files.pythonhosted.org/packages/a5/8d/97443f0dca4a03a0bc7629fd396fd494a1cb6666121e38c5075acb217d8f/ruff-0.17.0-py3-none-manylinux_2_17_ppc64le.manylinux2014_ppc64le.whl", hash = "sha256:a330178bdffc4205dbf3bda11d93e059e388fd6546f8cdd304501a9160363c0d", size = 11350129, upload-time = "2026-10-09T19:46:56.486Z" },
    { url = "https://files.pythonhosted.org/packages/9c/0a/c525efd9777be4b6b012e6969a3012648468e7e6c4b3e5b46af69f46e8eb/ruff-0.17.0-py3-none-manylinux_2_17_s390x.manylinux2014_s390x.whl", hash = "sha256:7bb08489e234876fa2da67ae3ea938e9a2156da80293e0e4365abd6973d98329", size = 10906223, upload-time = "2026-10-09T19:47:00.263Z" },
    { url = "https://files.pythonhosted.org/packages/2c/3c/4a01195d93420cad1175bedad13a515dc8a56f95a6e39789b92e582682f5/ruff-0.17.0-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl", hash = "sha256:bc73e7c133e82d55b5f15897b2a442d72c0cb4a0c886c46801ce3c247150b60c", size = 10386314, upload-time = "2026-10-09T19:47:03.057Z" },
    { url = "https://files.pythonhosted.org/packages/c7/72/1a3951665485a921f6375f91e754a1854d5a645d41acc3642668064ff64d/ruff-0.17.0-py3-none-manylinux_2_31_riscv64.whl", hash = "sha256:db4f74c533403ab70fe4007873f6ae0c9f94a8b03158cf48d78788e47cdbe399", size = 10565464, upload-time = "2026-10-09T19:47:05.831Z" },
    { url = "https://files.pythonhosted.org/packages/90/8c/539b4d8c082f57e18db8ae2be85a460d77861c79dcd5798e32b536a6a06f/ruff-0.17.0-py3-none-musllinux_1_2_aarch64.whl", hash = "sha256:3d8cc360e666d1914e47b0777c6906d70cf18891a55532bd0a16844195d70859", size = 10079468, upload-time = "2026-10-09T19:47:08.617Z" },
    { url = "https://files.pythonhosted.org/packages/e0/b8/84286966db79434e8c26b585b0a0f6897cb3ab1c51a4aa4df10c28488b62/ruff-0.17.0-py3-none-musllinux_1_2_armv7l.whl", hash = "sha256:d66de796b726c4801e05fa99a2a8d7a780e107be222486c304ab61765561e866", size = 9958556, upload-time = "2026-10-09T19:47:11.324Z" },
    { url = "https://files.pythonhosted.org/packages/69/50/27b6eed27b83fcdd5bfa0d52b83231e29094754374698da404d094487ae3/ruff-0.17.0-py3-none-musllinux_1_2_i686.whl", hash = "sha256:c3f268baf004aea944f040623327119527ea231af15f7fb7890e82cea0679589", size = 10352173, upload-time = "2026-10-09T19:47:14.188Z" },
    { url = "https://files.pythonhosted.org/packages/2a/fa/955399fd13044cd827862044117d784a59e3196f6cce7424908ac9a7f914/ruff-0.17.0-py3-none-musllinux_1_2_x86_64.whl", hash = "sha256:864b6c1acb6b0bccf94b5a3938a1531fd09aaca5e5659a2e7bf0f3cf2a685540", size = 10791761, upload-time = "2026-10-09T19:47:16.931Z" },
    { url = "https://files.pythonhosted.org/packages/ae/bf/024e01e1f6aec87768696725e648ed5b438941341eea8f8100beb681961f/ruff-0.17.0-py3-none-win32.whl", hash = "sha256:5e50aa5b84decd9fe5b0bb0e6f71c3b592f1767ed09faa4b7207d933961e35cd", size = 9904112, upload-time = "2026-10-09T19:47:19.75Z" },
    { url = "https://files.pythonhosted.org/packages/cc/77/1ee73df41dcc8d1cdb686ee4bc46ea29704ea175feb6b95c78420f631ab8/ruff-0.17.0-py3-none-win_amd64.whl", hash = "sha256:8ab76bcda86dfd28e13776cb5de3c7bcdcf1ae3d37ed761113d1a5a415dc134c", size = 10115585, upload-time = "2026-10-09T19:47:22.698Z" },
    { url = "https://files.pythonhosted.org/packages/fd/71/eb4f0ccc844aece56963e8578df9c95d4c00f580547d52329d4035d3af18/ruff-0.17.0-py3-none-win_arm64.whl", hash = "sha256:c154c73ff43f9854395e24cac507af13078962e53d2b511605058d22af1fdb88", size = 9872035, upload-time = "2026-10-09T19:47:26.306Z" },
]

[[package]]
name = "shellingham"
version = "1.5.4"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/packages/58/15/8b3609fd3830ef7b27b655beb4b4e9c62313a4e8da8c676e142cc210d58e/shellingham-1.5.4.tar.gz", hash = "sha256:8dbca0739d487e5bd35ab3ca4b36e11c4078f3a234bfce294b0a0291363404de", size = 10310, upload-time = "2023-10-24T04:13:40.426Z" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/e0/f9/0595336914c5619e5f28a1fb793285925a8cd4b432c9da0a987836c7f822/shellingham-1.5.4-py2.py3-none-any.whl", hash = "sha256:7ecfff8f2fd72616f7481040475a65b2bf8af90a56c89140852d1120324e8686", size = 9755, upload-time = "2023-10-24T04:13:38.866Z" },
]

[[package]]
name = "sniffio"
version = "1.3.1"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/packages/a2/87/a6771e1546d97e7e041b6ae58d80074f81b7d5121207425c964ddf5cfdbd/sniffio-1.3.1.tar.gz", hash = "sha256:f4324edc670a0f49750a81b895f35c3adb843cca46f0530f79fc1babb23789dc", size = 20372, upload-time = "2024-02-25T23:20:04.057Z" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/e9/44/75a9c9421471a6c4805dbf2356f7c181a29c1879239abab1ea2cc8f38b40/sniffio-1.3.1-py3-none-any.whl", hash = "sha256:2f6da418d1f1e0fddd844478f41680e794e6051915791a034ff65e5f100525a2", size = 10235, upload-time = "2024-02-25T23:20:01.196Z" },
]

[[package]]
name = "sse-starlette"
version = "3.3.3"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "anyio" },
    { name = "starlette" },
]
sdist = { url = "https://files.pythonhosted.org/packages/14/2f/9223c24f568bb7a0c03d751e609844dce0968f13b39a3f73fbb3a96cd27a/sse_starlette-3.3.3.tar.gz", hash = "sha256:72a95d7575fd5129bd0ae15275ac6432bb35ac542fdebb82889c24bb9f3f4049", size = 32420, upload-time = "2026-03-17T20:05:55.529Z" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/78/e2/b8cff57a67dddf9a464d7e943218e031617fb3ddc133aeeb0602ff5f6c85/sse_starlette-3.3.3-py3-none-any.whl", hash = "sha256:c5abb5082a1cc1c6294d89c5290c46b5f67808cfdb612b7ec27e8ba061c22e8d", size = 14329, upload-time = "2026-03-17T20:05:54.35Z" },
]

[[package]]
name = "starlette"
version = "1.3.1"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "anyio" },
    { name = "typing-extensions", marker = "python_full_version < '3.13'" },
]
sdist = { url = "https://files.pythonhosted.org/packages/eb/e3/7c1dc7381d9f8ab7d854328ebfa884e62cb3f3d8549ddfd37c7814f42afa/starlette-1.3.1.tar.gz", hash = "sha256:05d0213193f2fbaae60e2ecb593b4add4262ad4e46536b54abe36f11a71724e0", size = 2703240, upload-time = "2026-06-12T09:23:11.602Z" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/ec/bb/2799cc2ede3ed41131f8975621e7213dfc7ef4acbbaadfa440f32500c370/starlette-1.3.1-py3-none-any.whl", hash = "sha256:c7372aae11c3c3f26a42df7bd626cec2f47d03483d261d369516a615a53714c6", size = 73632, upload-time = "2026-06-12T09:23:10.017Z" },
]

[[package]]
name = "ty"
version = "0.0.86"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/packages/f1/fa/9b35728cc3c04d64f434c656836fa3c5f6e384a7813e48e63245510d5c69/ty-0.0.86.tar.gz", hash = "sha256:6edcaf52e207d653873d5f495c1a8470075b232030714c981f07f0a1075bc343", size = 7911723, upload-time = "2026-10-09T22:20:57.83Z" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/95/27/dd422283667ce10d60af57edc3ccab078084282ee304a5c22b5ed79390c6/ty-0.0.86-py3-none-linux_armv6l.whl", hash = "sha256:305c238df5dedf97f1b65e52d2c446a41d11551291e37054858c00c5627bf15b", size = 14159390, upload-time = "2026-10-09T22:20:17.583Z" },
    { url = "https://files.pythonhosted.org/packages/57/e3/838ea547c177983976103d3a54b346afc22d0ff97943ab58c7b7aff1f753/ty-0.0.86-py3-none-macosx_10_12_x86_64.whl", hash = "sha256:27a8a7cf26a1cd17d93586eb20aadbcc535fa6ad4b535813ee8fc52560c31efd", size = 13684426, upload-time = "2026-10-09T22:20:19.939Z" },
    { url = "https://files.pythonhosted.org/packages/bc/62/dfde84ffab702545f866350675b16f8df6555d3c41123c25e7a509fe857e/ty-0.0.86-py3-none-macosx_11_0_arm64.whl", hash = "sha256:40e5fc602af41b0ea89dd1d19fe8da7e75322e6e0db95ea23340a858b409ac2b", size = 12845457, upload-time = "2026-10-09T22:20:21.979Z" },
    { url = "https://files.pythonhosted.org/packages/47/b2/7e0e7ffc8b3961f5f74893ba9b98433b922d3f1ae6621d1e3e3e20663e1d/ty-0.0.86-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", hash = "sha256:c4b525ce4feb60aa2dd6becae4c470daea889149ba9dc7699ffbcf41448f69a9", size = 13656310, upload-time = "2026-10-09T22:20:24.544Z" },
    { url = "https://files.pythonhosted.org/packages/e7/c8/977594e024d154f0e064b48a6f7e39a0e1e55a524349dba22146f01e02db/ty-0.0.86-py3-none-manylinux_2_17_armv7l.manylinux2014_armv7l.whl", hash = "sha256:a000ddcc0b99bd1ab8c8277630711061a36ae83395780fdb935bad540ebe7103", size = 13887036, upload-time = "2026-10-09T22:20:26.844Z" },
    { url = "https://files.pythonhosted.org/packages/3a/75/67e8e7bf89a6be7535768380cb20569b460b89cb09d5c82ce27411782786/ty-0.0.86-py3-none-manylinux_2_17_i686.manylinux2014_i686.whl", hash = "sha256:ea3848f3cab206e9798e5a9f7c4ce8a80297b0a88ba9aa8a091360a298e97424", size = 14805103, upload-time = "2026-10-09T22:20:29.274Z" },
    { url = "https://files.pythonhosted.org/packages/a1/14/a7f3b88cc76156feaf5d48601bd5da96a116f846ad0abc526df03a735bcc/ty-0.0.86-py3-none-manylinux_2_17_ppc64le.manylinux2014_ppc64le.whl", hash = "sha256:087bad6ae8fa7248a16c01f5646c121dccaacbaf320ff544eed4e8c5c1fd7555", size = 15203931, upload-time = "2026-10-09T22:20:31.736Z" },
    { url = "https://files.pythonhosted.org/packages/a7/23/42f6ad5d4bb7091d70a0e96d7d436d6bc9a490210a928727dde5d883ed26/ty-0.0.86-py3-none-manylinux_2_17_s390x.manylinux2014_s390x.whl", hash = "sha256:fe7f2721746c9ee64626c69da9245faedc0f375024bf41458e45eb7b28fe5f63", size = 15094434, upload-time = "2026-10-09T22:20:34.269Z" },
    { url = "https://files.pythonhosted.org/packages/d1/b8/211781d3c8de5fa88437412b7a8c0d7a632596033cff51d5004b08e94e1c/ty-0.0.86-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl", hash = "sha256:a5c18501c54874149d05e5199211146876afeaeee2af234042e56dccc9d5812a", size = 14436812, upload-time = "2026-10-09T22:20:36.795Z" },
    { url = "https://files.pythonhosted.org/packages/b2/2a/518cc7ef2586384345be675d470e0087591810304b5d994d0a2194c7d68e/ty-0.0.86-py3-none-manylinux_2_31_riscv64.whl", hash = "sha256:0a48967c8adba6b12035243f225a0585b0bc5f0bf940a4829876bc455ebf3d2f", size = 14671116, upload-time = "2026-10-09T22:20:39.277Z" },
    { url = "https://files.pythonhosted.org/packages/7a/18/a820553ad3206d0cdfad5866dd64939c7e3be73e891d88c73f7fd3acb5d6/ty-0.0.86-py3-none-musllinux_1_2_aarch64.whl", hash = "sha256:561a4eae98f6ff05395e8d7be8151fdb328eeaead1ac63dc721ca891623f7924", size = 13586361, upload-time = "2026-10-09T22:20:41.444Z" },
    { url = "https://files.pythonhosted.org/packages/22/58/f1700176e6ae4d0a3d25e447734c60ca464d6e76ed2e8a32920ebd41e523/ty-0.0.86-py3-none-musllinux_1_2_armv7l.whl", hash = "sha256:ccad053ce880a1f8c0850d9dd1f277f3ee559a98bded3f93472268376ceccc2d", size = 13900289, upload-time = "2026-10-09T22:20:43.955Z" },
    { url = "https://files.pythonhosted.org/packages/59/86/2f0e3c9a055f8606911a80311763a089784b66af22dd80fd3290e3b167c6/ty-0.0.86-py3-none-musllinux_1_2_i686.whl", hash = "sha256:7c16d22857bad1da56b147bf53ef0ed2252d7677dc5e7ee51c757b2e52ab6351", size = 14235785, upload-time = "2026-10-09T22:20:46.401Z" },
    { url = "https://files.pythonhosted.org/packages/b4/1d/72fa2347b641143b0440296144a65f424fe047302cb13af059988f1de7a4/ty-0.0.86-py3-none-musllinux_1_2_x86_64.whl", hash = "sha256:d863f8f190e96878ed1900a8a6d5093f37761c0c47409e2bdb3d9370e37471e1", size = 14559840, upload-time = "2026-10-09T22:20:48.753Z" },
    { url = "https://files.pythonhosted.org/packages/47/4a/a798be4aee4ea0bb427c22f157945d0ac41310f4d6e058b3758dfb859451/ty-0.0.86-py3-none-win32.whl", hash = "sha256:1ac3d8fe9efae04fbf1407583ed4118e0364a45b49a020d62b202846695a2ba1", size = 13133227, upload-time = "2026-10-09T22:20:51.034Z" },
    { url = "https://files.pythonhosted.org/packages/c7/a0/c9d585fa1c5bf4ed2727f576f1542bc13e268f036451a79d057c249fc26f/ty-0.0.86-py3-none-win_amd64.whl", hash = "sha256:6fe4116fb1a7ad3c4f7804d9241dc81187717fbd9f5fed5b50e2752a20e17a67", size = 13665391, upload-time = "2026-10-09T22:20:53.237Z" },
    { url = "https://files.pythonhosted.org/packages/2a/7e/d9811358bce1e54ac1b93bd44f4c45eba5e2e92672c5410248776c54319e/ty-0.0.86-py3-none-win_arm64.whl", hash = "sha256:0df36f494c5d07f68ebec3edb74fc719c4c959db7061c2018f1dff2dfe62150b", size = 13237981, upload-time = "2026-10-09T22:20:55.586Z" },
]

[[package]]
name = "typer"
version = "0.27.3"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "annotated-doc" },
    { name = "colorama", marker = "sys_platform == 'win32'" },
    { name = "rich" },
    { name = "shellingham" },
]
sdist = { url = "https://files.pythonhosted.org/packages/03/51/d33db42cc72ffd8c30777547b42d01f0cbf9d95a770457698d0174b3ed71/typer-0.27.3.tar.gz", hash = "sha256:d0396f770a560ab1b0a8504e13b5f254b728cedb05c61cf0359e944e50ce8901", size = 205303, upload-time = "2026-10-06T17:24:16.61Z" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/07/ea/2e31b67051e91a133189e9c000c222502ddc6969856416de0d095de4c0b0/typer-0.27.3-py3-none-any.whl", hash = "sha256:e50022f28b82a86313e54501317a1db64bf8f8d036ff8cfe5ca7e47675454aff", size = 123312, upload-time = "2026-10-06T17:24:15.054Z" },
]

[[package]]
name = "typing-extensions"
version = "4.16.0"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/packages/f6/cc/6253133b5bb138fc3306cebfbda2c520f545d36b5be2c7255cc528bb45d6/typing_extensions-4.16.0.tar.gz", hash = "sha256:dc983d19a509c94dba722ee6abd33940f7c05a89e243c47e907eb4db6f1a43e5", size = 113555, upload-time = "2026-07-02T08:40:05.92Z" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/49/d3/b8441a820a491ddfc024b0b0cf0393375b75ea13866d9c66727e54c2fc80/typing_extensions-4.16.0-py3-none-any.whl", hash = "sha256:481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8", size = 45571, upload-time = "2026-07-02T08:40:04.659Z" },
]

[[package]]
name = "typing-inspection"
version = "0.4.4"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "typing-extensions" },
]
sdist = { url = "https://files.pythonhosted.org/packages/a3/26/b09b8010994eccc3c09092e6b34058f36a460eea2d4c3e8b910c695975a0/typing_inspection-0.4.4.tar.gz", hash = "sha256:547274fa6b0a561ccf549cc9524b999a578e737d015d8709d021f9d0d13bea47", size = 76928, upload-time = "2026-08-12T12:37:25.997Z" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/67/81/4add07e5172b7ac40d8ed5ff580409a7801a4fe26d529bdd915401dabfbe/typing_inspection-0.4.4-py3-none-any.whl", hash = "sha256:65b8397ba37ccbce054456aaccddfc91e6e3083c92824df348d96ca832f3f147", size = 14750, upload-time = "2026-08-12T12:37:24.648Z" },
]

[[package]]
name = "uvicorn"
version = "0.42.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "click" },
    { name = "h11" },
]
sdist = { url = "https://files.pythonhosted.org/packages/e3/ad/4a96c425be6fb67e0621e62d86c402b4a17ab2be7f7c055d9bd2f638b9e2/uvicorn-0.42.0.tar.gz", hash = "sha256:9b1f190ce15a2dd22e7758651d9b6d12df09a13d51ba5bf4fc33c383a48e1775", size = 85393, upload-time = "2026-03-16T06:19:50.077Z" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/0a/89/f8827ccff89c1586027a105e5630ff6139a64da2515e24dafe860bd9ae4d/uvicorn-0.42.0-py3-none-any.whl", hash = "sha256:96c30f5c7abe6f74ae8900a70e92b85ad6613b745d4879eb9b16ccad15645359", size = 68830, upload-time = "2026-03-16T06:19:48.325Z" },
]
