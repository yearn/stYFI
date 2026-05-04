# stYFI

## Core components

### Reward Distributor
The **RewardDistributor**'s task is to distribute token rewards each epoch to a set of components, distributing them proportionally to each component according to their self reported weight. Rewards for epoch `N` are claimable by each component in epoch `N+1` onward. Rewards are claimed in order.
Anyone is allowed to schedule rewards for a future epoch by depositing them into the contract. The contract can also pull in tokens from another contract, if configured.

The components that are intended to be added at launch are:
- StakingRewardDistributor
- LiquidLockerRewardDistributor
- VotingEscrowRewardDistributor

### Staked YFI
The **StakedYFI** contract is a ERC4626 vault that is 1:1 to the underlying token, YFI. It reports user operations to a hook. It does not allow instant withdrawals, except for addresses whitelisted by the hook. Unstaking burns the vault shares immediately and gradually releases the underlying tokens over a streaming period.

### Staking Middleware
**StakingMiddleware** is a contract that is supposed to be configured as the StakedYFI hook address. It contains a configurable list of addresses that are blacklisted from transfering their stYFI (unstaking is still allowed) as well as a list of addresses that are allowed to bypass the unstaking stream. It passes all operation hooks down to two configured addresses, which are intended to be the StakingRewardDistributor and the WeightAggregator.

### Staking Reward Distributor
The **StakingRewardDistributor** will receive staking hook updates from the middleware. The contract snapshots the total amount of YFI staked each epoch to report as weight to the RewardDistributor. It will claim rewards as they become available, and stream them to stakers over the following epoch proportionally to their current balance. Rewards expire after a configurable number of epochs, after which they can be reclaimed by anyone, optionally with a bounty to the caller.

### Liquid Locker Depositor
Each of the three veYFI liquid lockers (LL) will have an instance of the **LiquidLockerDepositor** contract deployed, with their token as the underlying. It is a ERC4626 token that has a `1:S` ratio with the underlying, where `S` is set on deployment and is supposed to be equal to the amount of LL tokens divided by the amount of YFI they represent.
The token cannot be transfered and much like stYFI has an unstaking period. It also reports staking and unstaking operations to a hook contract.

### Liquid Locker Middleware
Each instance of **LiquidLockerMiddleware** is supposed to be configured as hook address of a LiquidLockerDepositor. It passes all hooks down to two configured addresses, which are intended to be the LiquidLockerRewardDistributor and the WeightAggregator.

### Liquid Locker Reward Distributor
The **LiquidLockerRewardDistributor** will be set as the hook contract in each of the 3 LL middlewares. Similar to the reward distributor for stYFI, it claims tokens from the global reward distributor as they become available. However, the weight that is reported is not determined by the amount of staked tokens but rather by a preconfigured total weight and a decaying boost on top. Each of the 3 LLs have their own relative weight, which determines the share of the total rewards their stakers will receive.

### Weight Aggregator
The **WeightAggregator** is designed to receive state updates from hooks on stYFI and the three llYFI components. It will keep track of the summed staked balance of every user and has two distinct usecases:
- The contract tracks a vote weight for every user that can be used in a governance system. Increases in staking balance cause the vote weight to ramp up to the full value over 4 epochs
- The aggregated balance and its changes are forwarded to the YBCWeightAggregator, where it can be used for YBC yield redistribution and voting purposes. Crucially the staking supply in these forwarded messages no longer include the supply of the individual component, rather they are replaced by the aggregated supply

Since this aggregator is deployed after launch, it has to be manually activated once. When activated it computes the total staked amount across all users and stores the value. In order for this contract to behave as expected the new middlewares should be injected atomically with the activation.

### Liquid Locker Redemption
The **LiquidLockerRedemption** contract is a facility to allow anyone to exchange their LL tokens for YFI, at a fee that decays over time. It also allows anyone to move in the opposite direction at no fee, if there are any LL tokens available. Each token has a configurable capacity set, which is used up whenever LL tokens are redeemed and freed back up whenever the LL tokens are bought back.

### Voting Escrow Snapshot
Each of the veYFI locks (except the LLs) will have their veYFI balance and unlock time at the snapshot block recorded in **VotingEscrowSnapshot**. When querying this contract for a snapshotted lock it will check the veYFI contract and only report a lock if the user did not perform an early exit.

### Voting Escrow Reward Distributor
The **VotingEscrowRewardDistributor** is another component in the reward distributor, and reports a weight based on users with a veYFI lock snapshot that have migrated. Each migrated user has a weight equal to the amount of YFI in their lock and an individual decaying boost on top, based on the duration of their lock at time of snapshot. Any user early exiting out of their veYFI lock will lose their claim on future rewards and will have their unclaimed historical rewards reclaimed.

### Delegated Staked YFI
The **DelegatedStakedYFI** contract is another ERC4626 1:1 with YFI. It deposits the YFI into the StakedYFI contract and works with the assumption that it is configured to bypass its unstaking stream. This contract maintains its own unstaking stream which is functionally equivalent to StakedYFI. It also reports its own state changing operations (transfer/stake/unstake) to a hook contract.

### Delegated Staking Reward Distributor
The **DelegatedStakingRewardDistributor** will be the hook contract in the delegated staked YFI contract. Unlike the other distributors it is NOT intended to be a component in the global reward distributor. Instead it acts like a regular depositor into stYFI and claims rewards directly from the StakingRewardDistributor, and should be whitelisted there as such. Rewards are claimed on each user operation and are distributed proportionally according to the staked balances.

### Reward Claimer
None of the reward distributors support direct interactions from end users to claim their rewards. Instead the **RewardClaimer** is the user facing contract. It will claim rewards on their behalf from all the components at once.

The components that will be added are:
- StakingRewardDistributor
- LiquidLockerRewardDistributor
- VotingEscrowRewardDistributor
- DelegatedStakingRewardDistributor
- YBCRewardDistributor

## Yearn Builder Collective (YBC)

### YBC
The **YBC** contract maintains the official list of members of the Collective. The contract is also supposed to hold the Collective's staking positions in stYFI and/or llYFI.
Outside adddresses can be whitelisted as operators, which allows them to call contracts on behalf of the YBC. This allows for a modular deployment of the YBC that can be iterated on if required.

Operators are also allowed to add and remove members to the YBC. These operations are also forwarded to a hook contract, which will be the YBCWeightAggregator.

The modules that will be added as operator are:
- YBCElection
- YBCRewardDistributor

### YBC Weight Aggregator
Sitting downstream from the global WeightAggregator, the **YBCWeightAggregator** is designed to aggregate staked stYFI and llYFI balances and voting weight for YBC members specifically. It is also supposed to receive membership updates from the YBC.

All upstream operations are translated as follows, depending on the membership of the involved users:
- Add member: treat as staking operation of entire balance
- Remove member: treat as unstaking operation of entire balance
- Transfer:
    - YBC -> YBC: treat as-is
    - YBC -> non-YBC: treat as unstaking operation
    - non-YBC -> YBC: treat as staking operation
    - non-YBC -> non-YBC: ignore
- Stake/unstake by YBC member: treat as-is
- Stake/unstake by non-YBC member: ignore

The translated operations are processed inside the aggregator and also forwarded further.

Much like the global weight aggregator this contract also keeps track of a weight. Note that this weight can be different from the global weight depending on the timing of when the user is added to the YBC.

### YBC Reward istributor
The **YBCRewardDistributor** will be added as YBC operator. As recipient of state updates from the YBCWeightAggregator, rewards are claimed from the YBC during each state change and redistributed according to each member's aggregated staked balance.

This component is supposed to be added to the RewardClaimer, allowing YBC members to seemlessly claim rewards from the YBC without any additional manual action.

### YBC Election
Membership of the Collective is regulated by the **YBCElection** contract. Any current member can nominate anyone else to be added to the Collective. Any current member can also nominate any member for expulsion from the Collective.

A proposal made in epoch `N-1` can be retracted in the same epoch and can be voted on in the second half of epoch `N`, leaving at least 1 week of discussion for any proposal. All YBC members are allowed to vote once on each proposal, with their vote weight determined by the YBCWeightAggregator. The only exception is that members are not allowed to vote on their own expulsion. To prevent last second manipulation, vote weights decay from full to 0 in the last 24 hours.

The vote ends at the end of epoch `N`. If a threshold fraction of votes is in favor of the proposal, the proposal is considered passed. Addition and expulsion votes have their own distinct configurable thresholds.

A passed proposal can be executed by anyone during epoch `N+1`. If a passed proposal is not executed during that epoch, it will become expired and cannot be executed anymore.

### YBC Bonus Recipient
The **YBCBonusRecipient** is a simple helper contract that takes in YFI deposits and stakes it into stYFI for the YBC.

## Call flowchart
```mermaid
flowchart TD
    U[User]
    A[RewardDistributor]
    B[StakingRewardDistributor]
    D[VotingEscrowRewardDistributor]
    C[LiquidLockerRewardDistributor]

    E[stYFI] --> |"on state change"| J
    G[stYFIx] --> E
    F["llYFI (x3)"] --> |"on state change"| K

    G --> |"on state change"| H[DelegatedStakingRewardDistributor]
    H --> |"claim"| B

    Y[Yearn] --> |"deposit rewards"|A

    B --> |"claim"| A
    D --> |"claim"| A
    C --> |"claim"| A

    I["RewardClaimer"]
    I --> |"claim"| B
    I --> |"claim"| D
    I --> |"claim"| C
    I --> |"claim"| H
    I --> |"claim"| N
    U --> |"claim rewards"| I

    U --> |"stake"| E
    U --> |"stake"| G
    U --> |"stake"| F

    J[stYFI middleware]
    J --> B
    J --> L

    K["llYFI middleware (x3)"]
    K --> C
    K --> L

    L[WeightAggregator]
    M[YBCWeightAggregator]
    L --> |"iff YBC member"| M

    N[YBCRewardDistributor]
    M --> |sync| N
    N --> |claim| P

    P[YBC]
    O[YBCElection]
    O --> |"on election"| P
```

## Usage

### Install dependencies
```sh
# Install foundry
curl -L https://foundry.paradigm.xyz | bash
foundryup
# Install ape
pip install eth-ape
# Install required ape plugins
ape plugins install .
```

### Run tests
```sh
ape test
```
