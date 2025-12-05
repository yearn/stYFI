Audit Findings – stYFI
======================

Scope: Vyper contracts in `contracts/` (RewardDistributor, StakedYFI, StakingMiddleware, StakingRewardDistributor, DelegatedStakedYFI, DelegatedStakingRewardDistributor, LiquidLockerDepositor, LiquidLockerRewardDistributor, LiquidLockerRedemption, VotingEscrowSnapshot, VotingEscrowRewardDistributor, RewardClaimer).

Critical / High
---------------
- VotingEscrowRewardDistributor `report()` uses `snapshot.locked(msg.sender)` instead of `_account`, so any caller without a veYFI lock can slash any migrated user, zero their lock, and take the bounty.
- VotingEscrowRewardDistributor weight calc underflows once `epoch > lock.boost_epochs`; `lock.amount // MAX_NUM_EPOCHS * (lock.boost_epochs - epoch)` goes negative, causing every claim/reclaim/report to revert and freezing rewards. Clamp at zero.
- 32-epoch (~448d) hard caps on catch-up loops (`RewardDistributor._sync`, `StakingRewardDistributor._sync_integral`, `LiquidLockerRewardDistributor._sync_rewards/_sync_integral`, `VotingEscrowRewardDistributor._sync_rewards/_sync_total_weights/_claim`) make claims/hooks revert after long inactivity until multiple syncs are run. DoS risk via neglect; remove or allow partial progress without revert.

Medium / Operational
--------------------
- Claimer model: StakingRewardDistributor and DelegatedStakingRewardDistributor pay rewards to the claimer, not the user. Misconfigured/malicious claimers can withhold or steal rewards. Restrict claimers to trusted surfaces (e.g., RewardClaimer) and monitor whitelist changes.
- StakingRewardDistributor uses a permanent 1e12 dust weight, slightly diluting user rewards. Remove if full allocation desired.
- StakingMiddleware blacklist only blocks senders; blacklisted addresses can still receive and accrue via transfers from non-blacklisted senders. Confirm intent; block receivers too if needed.
- LiquidLockerRewardDistributor weight/unstake paths assert full sync; >32-epoch gaps halt staking/unstaking until catch-up is done. Document required ops or relax caps.
- LiquidLockerDepositor `withdraw(_assets)` floors to `_assets // scale`; if `_assets` not a multiple of `scale`, the function returns `_assets` but only transfers the floored amount. Consider requiring multiples or returning the actual transferred amount.
- RewardClaimer assumes component `claim` pays `msg.sender`; if any component deviates, users get nothing. Keep components consistent or add reentrancy guards.
- LiquidLockerRedemption: management can move any token and set fee/capacity; trust required. `exchange` can underflow `used` if called before any redemption; add guard or clearer error.

Integration Notes / Reward Path
-------------------------------
- Staking path: stYFI → Middleware → StakingRewardDistributor hooks update weights before supply changes; rewards for epoch N stream over epoch N+1. Ensure `distributor` and `depositor` are set and claimers whitelisted.
- Delegated stYFI: DelegatedStakedYFI assumes instant-withdraw upstream; DelegatedStakingRewardDistributor claims directly from StakingRewardDistributor. Mis-whitelisting blocks users.
- Liquid lockers: LiquidLockerDepositor hooks drive LiquidLockerRewardDistributor; rewards split by normalized weights with decaying boost. Weight updates can instantly reroute rewards; ensure governance controls and monitoring.
- veYFI migration: relies on VotingEscrowSnapshot integrity; current `report` bug enables arbitrary slashing, and boost underflow can freeze claims. Fix both to keep rewards flowing.
