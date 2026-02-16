from dataclasses import dataclass
from typing import List, Tuple, Literal, Optional, Dict, Any
import math
import time
import os
import json
import multiprocessing as mp

import numpy as np

from GameController import GameController
from ai.AI import AI
from ai.RuleBasedAI import RuleBasedAI
from game.Player import PlayerNumber
from view.HeadlessView import HeadlessView

HAS_MPL = False
plt = None
try:
    import matplotlib.pyplot as plt  # type: ignore
    HAS_MPL = True
except Exception:
    HAS_MPL = False
    plt = None


def corr_from_cov(C: np.ndarray) -> np.ndarray:
    d = np.sqrt(np.clip(np.diag(C), 1e-20, np.inf))
    return C / np.outer(d, d)


def plot_corr_heatmap(corr: np.ndarray, names: List[str], title: str, out_path: Optional[str] = None):
    if not HAS_MPL or plt is None:
        return
    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(corr, vmin=-1, vmax=1)

    ax.set_title(title)
    ax.set_xticks(np.arange(len(names)))
    ax.set_yticks(np.arange(len(names)))
    ax.set_xticklabels(names, rotation=90, fontsize=7)
    ax.set_yticklabels(names, fontsize=7)

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Correlation")

    fig.tight_layout()
    if out_path is not None:
        fig.savefig(out_path, dpi=200)
    plt.close(fig)


def plot_bar(values: np.ndarray, names: List[str], title: str, out_path: Optional[str] = None):
    if not HAS_MPL or plt is None:
        return
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(values))
    ax.bar(x, values)
    ax.set_title(title)
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=90, fontsize=7)
    fig.tight_layout()
    if out_path is not None:
        fig.savefig(out_path, dpi=200)
    plt.close(fig)


WeightKind = Literal["float", "int"]


@dataclass(frozen=True)
class WeightSpec:
    name: str
    kind: WeightKind
    default: float
    low: Optional[float] = None
    high: Optional[float] = None


WEIGHT_SPECS: List[WeightSpec] = [
    WeightSpec("INIT_PLACE_YIELD", "float", 1.0, 0.0, 5.0),
    WeightSpec("INIT_PLACE_DIVERSITY", "float", 0.5, 0.0, 5.0),
    WeightSpec("INIT_PLACE_BLOCK", "float", 0.3, 0.0, 5.0),

    WeightSpec("BUILD_SELF_UTILITY", "float", 1.0, 0.0, 5.0),
    WeightSpec("BUILD_OPPONENT_UTILITY", "float", 0.5, 0.0, 5.0),
    WeightSpec("BUILD_SPECIAL_UTILITY", "float", 0.3, 0.0, 5.0),
    WeightSpec("OPPONENT_INTERFERENCE_LEADING", "float", 0.8, 0.0, 5.0),

    WeightSpec("LR_BASE", "float", 0.2, 0.0, 5.0),
    WeightSpec("LR_PHASE", "float", 0.6, 0.0, 5.0),
    WeightSpec("LR_DISTANCE", "float", 1.0, 0.0, 5.0),
    WeightSpec("LR_CONTEST", "float", 0.8, 0.0, 5.0),

    WeightSpec("LA_BASE", "float", 0.2, 0.0, 5.0),
    WeightSpec("LA_PHASE", "float", 0.6, 0.0, 5.0),
    WeightSpec("LA_KNIGHT_DIST", "float", 1.0, 0.0, 5.0),
    WeightSpec("LA_CONTEST", "float", 0.8, 0.0, 5.0),

    WeightSpec("ROBBER_OWN_HEX_PENALTY", "float", 0.5, 0.0, 5.0),

    WeightSpec("LR_MIN_ROAD_LENGTH", "int", 5, 2, 15),
    WeightSpec("LR_UTILITY_MULTIPLIER", "float", 2.0, 0.0, 10.0),
    WeightSpec("LR_ROAD_THRESHOLD", "int", 4, 1, 15),

    WeightSpec("LA_MIN_KNIGHTS", "int", 3, 1, 10),
    WeightSpec("LA_ARMY_THRESHOLD", "int", 2, 0, 10),

    WeightSpec("TIME_DISCOUNT_RATE", "float", 0.1, 0.0, 2.0),

    WeightSpec("MAX_SETTLEMENTS_FOR_CITY_UPGRADE", "int", 2, 0, 10),
    WeightSpec("MIN_CANDIDATES_FOR_ROAD", "int", 3, 0, 20),
    WeightSpec("MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE", "int", 5, 0, 20),
    WeightSpec("START_VERTEX_EXPANSION_BONUS", "float", 0.05, 0.0, 1.0),
    WeightSpec("ATTENTION_LR_VP_THRESHOLD", "int", 7, 0, 20),

    WeightSpec("KNIGHT_DEFICIT_THRESHOLD", "int", 2, 0, 20),
    WeightSpec("LOW_KNIGHT_VALUE", "float", 0.1, 0.0, 10.0),
    WeightSpec("HIGH_KNIGHT_VALUE", "float", 2.0, 0.0, 10.0),
    WeightSpec("MEDIUM_KNIGHT_VALUE", "float", 0.5, 0.0, 10.0),
    WeightSpec("MIN_EXPECTED_VP_FOR_KNIGHT", "float", 0.2, 0.0, 5.0),

    WeightSpec("ETW_NO_ACTION_PENALTY", "float", 50.0, 0.0, 500.0),
    WeightSpec("ETW_MISSING_POINT_PENALTY", "float", 10.0, 0.0, 200.0),

    WeightSpec("LAMBDA_RISK_LEADER", "float", 0.5, 0.0, 5.0),
    WeightSpec("LAMBDA_RISK_BASE", "float", 0.3, 0.0, 5.0),
    WeightSpec("MAX_PLAYER_TRADE_GIVE_RATIO", "int", 4, 1, 20),
    WeightSpec("MIN_TRADE_ACCEPT_PROB", "float", 0.1, 0.0, 1.0),
    WeightSpec("ACCEPT_ETW_WEIGHT", "float", 1.0, 0.0, 10.0),
    WeightSpec("ACCEPT_COST_WEIGHT", "float", 0.5, 0.0, 10.0),
    WeightSpec("ACCEPT_HISTORY_WEIGHT", "float", 0.3, 0.0, 10.0),
    WeightSpec("CLOSE_OPPONENT_VP_GAP", "int", 2, 0, 20),
    WeightSpec("TRADE_LEADER_PENALTY", "float", 0.5, 0.0, 5.0),

    WeightSpec("ATTENTION_LR_EARLY_PENALTY", "float", 15.0, 0.0, 200.0),
    WeightSpec("DEV_CLOSE_THRESHOLD", "float", 0.08, 0.0, 1.0),
    WeightSpec("DIVERSION_BOOST", "float", 1.25, 0.0, 10.0),
]

NAMES = [w.name for w in WEIGHT_SPECS]
DIM = len(WEIGHT_SPECS)


class StrategyWeights:
    def __init__(self):
        for spec in WEIGHT_SPECS:
            if spec.kind == "int":
                setattr(self, spec.name, int(round(spec.default)))
            else:
                setattr(self, spec.name, float(spec.default))

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in NAMES}


def vec_from_defaults() -> np.ndarray:
    return np.array([float(spec.default) for spec in WEIGHT_SPECS], dtype=np.float64)


def clamp(v: float, low: Optional[float], high: Optional[float]) -> float:
    if low is not None and v < low:
        v = low
    if high is not None and v > high:
        v = high
    return v


def vec_to_weights(x: np.ndarray) -> StrategyWeights:
    w = StrategyWeights()
    for i, spec in enumerate(WEIGHT_SPECS):
        v = float(x[i])
        if not math.isfinite(v):
            v = float(spec.default)
        v = clamp(v, spec.low, spec.high)
        if spec.kind == "int":
            v = int(round(v))
            v = int(clamp(float(v), spec.low, spec.high))
        setattr(w, spec.name, v)
    return w


def splitmix64(x: int) -> int:
    x &= 0xFFFFFFFFFFFFFFFF
    x = (x + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    z = x
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9 & 0xFFFFFFFFFFFFFFFF
    z = (z ^ (z >> 27)) * 0x94D049BB133111EB & 0xFFFFFFFFFFFFFFFF
    z = z ^ (z >> 31)
    return z & 0xFFFFFFFFFFFFFFFF


def make_seed(*parts: int) -> int:
    x = 0x123456789ABCDEF0
    for p in parts:
        x = splitmix64(x ^ (p & 0xFFFFFFFFFFFFFFFF))
    return int(x & 0xFFFFFFFF)


@dataclass
class GameResult:
    candidate_won: bool
    candidate_vp: float
    baseline_vp: float


def run_game(*, seed: int, starting_position: int, candidate: StrategyWeights) -> GameResult:
    assert 0 <= starting_position < 4

    MAX_ATTEMPTS = 5
    attempt = 0
    current_seed = int(seed)

    class CandidatePolicy(RuleBasedAI):
        def __init__(self, rng):
            super().__init__(rng, weights=candidate)

    seats: List[PlayerNumber] = [
        PlayerNumber.P1,
        PlayerNumber.P2,
        PlayerNumber.P3,
        PlayerNumber.P4,
    ]

    while attempt < MAX_ATTEMPTS:
        player_policies: Dict[PlayerNumber, type[AI]] = {}
        for i, pn in enumerate(seats):
            player_policies[pn] = CandidatePolicy if i == starting_position else RuleBasedAI

        controller = GameController({}, player_policies, game_seed=current_seed)
        controller.view = HeadlessView()

        controller.start_game()
        game = controller.get_game_state()

        if game.game_over and not getattr(game, "timed_out", False):
            break

        attempt += 1
        current_seed = splitmix64(current_seed + attempt)

    else:
        return GameResult(
            candidate_won=False,
            candidate_vp=0.0,
            baseline_vp=10.0,
        )

    cand_player_number = seats[starting_position]
    cand_player = next(p for p in game.players if p.player_number == cand_player_number)

    def vp(p) -> float:
        return float(p.calc_victory_points()[1])

    cand_vp = vp(cand_player)

    others = [p for p in game.players if p.player_number != cand_player_number]
    other_vps = [vp(p) for p in others]
    baseline_vp = sum(other_vps) / len(other_vps) if other_vps else 0.0

    best_vp = max(vp(p) for p in game.players) if game.players else float("-inf")
    num_best = sum(1 for p in game.players if abs(vp(p) - best_vp) < 1e-9)
    candidate_won = (abs(cand_vp - best_vp) < 1e-9) and (num_best == 1)

    return GameResult(
        candidate_won=bool(candidate_won),
        candidate_vp=cand_vp,
        baseline_vp=baseline_vp,
    )


def fitness(r: GameResult) -> float:
    return (1.0 if r.candidate_won else 0.0) + 0.02 * (r.candidate_vp - r.baseline_vp)


def eval_pairs_for_generation(gen: int, num_base_seeds: int, positions_per_seed: int) -> List[Tuple[int, int]]:
    pairs: List[Tuple[int, int]] = []
    for k in range(num_base_seeds):
        s = make_seed(999, gen, k)
        for j in range(positions_per_seed):
            pairs.append((s, j % 4))
    return pairs


class CMAES:
    def __init__(self, m0: np.ndarray, sigma0: float, popsize: int, mu: int, seed: int):
        self.dim = int(m0.shape[0])
        self.m = m0.astype(np.float64).copy()
        self.sigma = float(sigma0)
        self.C = np.eye(self.dim, dtype=np.float64)

        self.lam = int(popsize)
        self.mu = int(mu)
        assert 1 <= self.mu <= self.lam

        self.rng = np.random.default_rng(seed)

        w = np.array([math.log(self.mu + 0.5) - math.log(i + 1) for i in range(self.mu)], dtype=np.float64)
        self.w = w / w.sum()
        self.mueff = (self.w.sum() ** 2) / (self.w ** 2).sum()

        d = self.dim
        self.cc = (4 + self.mueff / d) / (d + 4 + 2 * self.mueff / d)
        self.cs = (self.mueff + 2) / (d + self.mueff + 5)
        self.c1 = 2 / ((d + 1.3) ** 2 + self.mueff)
        self.cmu = min(1 - self.c1, 2 * (self.mueff - 2 + 1 / self.mueff) / ((d + 2) ** 2 + self.mueff))
        self.damps = 1 + 2 * max(0.0, math.sqrt((self.mueff - 1) / (d + 1)) - 1) + self.cs

        self.pc = np.zeros(d, dtype=np.float64)
        self.ps = np.zeros(d, dtype=np.float64)
        self.chiN = math.sqrt(d) * (1 - 1 / (4 * d) + 1 / (21 * d * d))

        self.gen = 0

    def ask(self) -> Tuple[np.ndarray, np.ndarray]:
        eigvals, eigvecs = np.linalg.eigh(self.C)
        eigvals = np.maximum(eigvals, 1e-20)
        C_sqrt = eigvecs @ np.diag(np.sqrt(eigvals)) @ eigvecs.T

        Z = self.rng.standard_normal(size=(self.lam, self.dim))
        Y = Z @ C_sqrt.T
        X = self.m[None, :] + self.sigma * Y
        return X, Z

    def tell(self, X: np.ndarray, f: np.ndarray):
        idx = np.argsort(-f)
        Xs = X[idx]
        m_old = self.m.copy()

        X_mu = Xs[: self.mu]
        self.m = (self.w[:, None] * X_mu).sum(axis=0)
        y = (self.m - m_old) / self.sigma

        eigvals, eigvecs = np.linalg.eigh(self.C)
        eigvals = np.maximum(eigvals, 1e-20)
        C_invsqrt = eigvecs @ np.diag(1.0 / np.sqrt(eigvals)) @ eigvecs.T

        self.ps = (1 - self.cs) * self.ps + math.sqrt(self.cs * (2 - self.cs) * self.mueff) * (C_invsqrt @ y)
        ps_norm = float(np.linalg.norm(self.ps))

        hsig = 1.0 if (ps_norm / math.sqrt(1 - (1 - self.cs) ** (2 * (self.gen + 1))) / self.chiN) < (
            1.4 + 2 / (self.dim + 1)
        ) else 0.0
        self.pc = (1 - self.cc) * self.pc + hsig * math.sqrt(self.cc * (2 - self.cc) * self.mueff) * y

        Y_mu = (X_mu - m_old[None, :]) / self.sigma
        rank_mu = np.zeros((self.dim, self.dim), dtype=np.float64)
        for i in range(self.mu):
            rank_mu += self.w[i] * np.outer(Y_mu[i], Y_mu[i])

        delta_hsig = (1 - hsig) * self.cc * (2 - self.cc)
        self.C = (
            (1 - self.c1 - self.cmu) * self.C
            + self.c1 * (np.outer(self.pc, self.pc) + delta_hsig * self.C)
            + self.cmu * rank_mu
        )

        self.sigma *= math.exp((self.cs / self.damps) * (ps_norm / self.chiN - 1.0))
        self.gen += 1


def fmt_seconds(s: float) -> str:
    s = max(0.0, float(s))
    if s < 60:
        return f"{s:.0f}s"
    m = s / 60.0
    if m < 60:
        return f"{m:.1f}m"
    h = m / 60.0
    return f"{h:.2f}h"


def _json_default(o: Any):
    if isinstance(o, (np.floating, np.float32, np.float64)):
        return float(o)
    if isinstance(o, (np.integer, np.int32, np.int64, np.uint32, np.uint64)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Not JSON serialisable: {type(o)}")


def save_best(out_dir: str, gen: int, best_f: float, best_x: np.ndarray, mean_x: np.ndarray, sigma: float):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "best_weights.json")
    obj = {
        "gen": gen,
        "best_fitness": best_f,
        "best_vec": best_x.tolist(),
        "best_weights": vec_to_weights(best_x).to_dict(),
        "mean_vec": mean_x.tolist(),
        "mean_weights": vec_to_weights(mean_x).to_dict(),
        "sigma": sigma,
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=_json_default)
    os.replace(tmp, path)


def save_checkpoint(
    out_dir: str,
    opt: CMAES,
    best_f: float,
    best_x: np.ndarray,
    done_games: int,
    all_X: List[np.ndarray],
    all_f: List[float],
):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "checkpoint.json")
    obj = {
        "opt": {
            "dim": opt.dim,
            "m": opt.m,
            "sigma": opt.sigma,
            "C": opt.C,
            "pc": opt.pc,
            "ps": opt.ps,
            "gen": opt.gen,
            "rng_state": opt.rng.bit_generator.state,
            "lam": opt.lam,
            "mu": opt.mu,
            "w": opt.w,
            "mueff": opt.mueff,
            "cc": opt.cc,
            "cs": opt.cs,
            "c1": opt.c1,
            "cmu": opt.cmu,
            "damps": opt.damps,
            "chiN": opt.chiN,
        },
        "best": {
            "best_f": best_f,
            "best_x": best_x,
        },
        "progress": {
            "done_games": done_games,
        },
        "eval_log": {
            "all_X": all_X,
            "all_f": all_f,
        },
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=_json_default)
    os.replace(tmp, path)


def load_checkpoint(out_dir: str) -> Optional[dict]:
    path = os.path.join(out_dir, "checkpoint.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_num_workers() -> int:
    env = os.environ.get("CMA_WORKERS", "").strip()
    if env:
        try:
            return max(1, int(env))
        except Exception:
            pass
    c = os.cpu_count() or 1
    return max(1, c - 1)


def _eval_one_game(task: Tuple[int, int, List[float]]) -> float:
    seed, pos, x_list = task
    x = np.array(x_list, dtype=np.float64)
    cand = vec_to_weights(x)
    r = run_game(seed=int(seed), starting_position=int(pos), candidate=cand)
    return float(fitness(r))


def main():
    GENERATIONS = 2
    POPSIZE = 8
    MU = 4
    SIGMA0 = 0.35
    NUM_BASE_SEEDS = 8
    POSITIONS_PER_SEED = 2
    SAVE_EVERY = 1

    OUT_DIR = "cma_es_out"

    os.makedirs(OUT_DIR, exist_ok=True)

    workers = pick_num_workers()
    ctx = mp.get_context("spawn")
    pool = ctx.Pool(processes=workers) if workers > 1 else None
    if pool is not None:
        print(f"Multiprocessing: {workers} workers")

    m0 = vec_from_defaults()

    ckpt = load_checkpoint(OUT_DIR)
    if ckpt is not None:
        print("Resuming from:", os.path.join(OUT_DIR, "checkpoint.json"))

        opt_state = ckpt["opt"]
        opt = CMAES(
            m0=m0,
            sigma0=float(opt_state["sigma"]),
            popsize=int(opt_state["lam"]),
            mu=int(opt_state["mu"]),
            seed=12345,
        )

        opt.m = np.array(opt_state["m"], dtype=np.float64)
        opt.sigma = float(opt_state["sigma"])
        opt.C = np.array(opt_state["C"], dtype=np.float64)
        opt.pc = np.array(opt_state["pc"], dtype=np.float64)
        opt.ps = np.array(opt_state["ps"], dtype=np.float64)
        opt.gen = int(opt_state["gen"])

        opt.w = np.array(opt_state["w"], dtype=np.float64)
        opt.mueff = float(opt_state["mueff"])
        opt.cc = float(opt_state["cc"])
        opt.cs = float(opt_state["cs"])
        opt.c1 = float(opt_state["c1"])
        opt.cmu = float(opt_state["cmu"])
        opt.damps = float(opt_state["damps"])
        opt.chiN = float(opt_state["chiN"])

        opt.rng = np.random.default_rng()
        opt.rng.bit_generator.state = opt_state["rng_state"]

        best_f = float(ckpt["best"]["best_f"])
        best_x = np.array(ckpt["best"]["best_x"], dtype=np.float64)
        done_games = int(ckpt["progress"]["done_games"])
        all_X = [np.array(v, dtype=np.float64) for v in ckpt["eval_log"]["all_X"]]
        all_f = [float(v) for v in ckpt["eval_log"]["all_f"]]
        start_gen = opt.gen
        t0 = time.time()
    else:
        opt = CMAES(m0=m0, sigma0=SIGMA0, popsize=POPSIZE, mu=MU, seed=12345)
        best_f = -1e18
        best_x = m0.copy()
        done_games = 0
        all_X: List[np.ndarray] = []
        all_f: List[float] = []
        start_gen = 0
        t0 = time.time()

    games_per_candidate = NUM_BASE_SEEDS * POSITIONS_PER_SEED
    total_games = GENERATIONS * POPSIZE * games_per_candidate

    print(f"Dim={DIM} weights. Games/candidate/gen={games_per_candidate}. Total games={total_games}.")
    if start_gen > 0:
        print(f"Continuing at gen={start_gen}/{GENERATIONS - 1} (done_games={done_games}).")

    for gen in range(start_gen, GENERATIONS):
        gen_start = time.time()
        pairs = eval_pairs_for_generation(gen, NUM_BASE_SEEDS, POSITIONS_PER_SEED)

        X, _Z = opt.ask()
        if not np.isfinite(X).all():
            raise RuntimeError("Non-finite candidate vector(s) sampled (NaN/Inf in X)")

        f = np.zeros(POPSIZE, dtype=np.float64)

        print(f"\n=== gen {gen}/{GENERATIONS - 1} | sigma={opt.sigma:.4f} ===")

        for i in range(POPSIZE):
            total = 0.0
            cand_start = time.time()

            tasks = [(int(seed), int(pos), X[i].tolist()) for (seed, pos) in pairs]

            if pool is None:
                for t in tasks:
                    total += _eval_one_game(t)
                    done_games += 1
            else:
                for val in pool.imap_unordered(_eval_one_game, tasks, chunksize=1):
                    total += float(val)
                    done_games += 1

            f[i] = total / len(pairs)

            all_X.append(X[i].copy())
            all_f.append(float(f[i]))

            cand_time = time.time() - cand_start
            elapsed = time.time() - t0
            rate = done_games / max(elapsed, 1e-9)
            eta = (total_games - done_games) / max(rate, 1e-9)

            print(
                f"  cand {i + 1:02d}/{POPSIZE}  "
                f"fitness={f[i]:.4f}  "
                f"cand_time={fmt_seconds(cand_time)}  "
                f"ETA_total={fmt_seconds(eta)}"
            )

        opt.tell(X, f)

        if (not np.isfinite(opt.C).all()) or (not math.isfinite(opt.sigma)) or (not np.isfinite(opt.m).all()):
            raise RuntimeError("Non-finite CMA-ES state after tell() (C/m/sigma contains NaN/Inf)")

        i_best = np.argmax(f).item()
        if float(f[i_best]) > best_f:
            best_f = float(f[i_best])
            best_x = X[i_best].copy()

        gen_time = time.time() - gen_start
        elapsed = time.time() - t0
        rate = done_games / max(elapsed, 1e-9)
        eta = (total_games - done_games) / max(rate, 1e-9)

        print(
            f"gen_done  best_gen={float(f[i_best]):.4f}  best_all={best_f:.4f}  "
            f"gen_time={fmt_seconds(gen_time)}  ETA_total={fmt_seconds(eta)}"
        )

        if (gen % SAVE_EVERY) == 0 or gen == GENERATIONS - 1:
            save_best(OUT_DIR, gen, best_f, best_x, opt.m, opt.sigma)

        save_checkpoint(
            out_dir=OUT_DIR,
            opt=opt,
            best_f=best_f,
            best_x=best_x,
            done_games=done_games,
            all_X=all_X,
            all_f=all_f,
        )

    if pool is not None:
        pool.close()
        pool.join()

    print("\nFinished.")
    print("Best fitness:", best_f)
    print("Best weights written to:", os.path.join(OUT_DIR, "best_weights.json"))
    print("Checkpoint written to:", os.path.join(OUT_DIR, "checkpoint.json"))

    corrC = corr_from_cov(opt.C)

    corr_w_f = None
    if len(all_X) >= 2:
        Xmat = np.vstack(all_X)
        fvec = np.array(all_f, dtype=np.float64)
        if np.isfinite(Xmat).all() and np.isfinite(fvec).all():
            M = np.hstack([Xmat, fvec[:, None]])
            C = np.corrcoef(M, rowvar=False)
            corr_w_f = C[-1, :-1]
            corr_w_f = np.nan_to_num(corr_w_f, nan=0.0, posinf=0.0, neginf=0.0)

    if HAS_MPL and plt is not None:
        plot_corr_heatmap(
            corrC,
            NAMES,
            title="CMA-ES weight correlation (from covariance C)",
            out_path=os.path.join(OUT_DIR, "corr_cmaes_C.png"),
        )
        if corr_w_f is not None:
            plot_bar(
                corr_w_f,
                NAMES,
                title="Weight vs fitness correlation (logged evals)",
                out_path=os.path.join(OUT_DIR, "corr_weight_fitness.png"),
            )
    else:
        data_path = os.path.join(OUT_DIR, "plot_data.json")
        obj = {
            "names": NAMES,
            "corr_cmaes_C": corrC.tolist(),
            "corr_weight_fitness": None if corr_w_f is None else corr_w_f.tolist(),
        }
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, default=_json_default)
        print("Wrote plot data to:", data_path)


if __name__ == "__main__":
    mp.freeze_support()
    main()
