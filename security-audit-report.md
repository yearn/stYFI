# Smart Contract Security Audit Report

## stYFI Protocol - Vyper Smart Contracts

**Audit Date:** December 4, 2025
**Language:** Vyper 0.4.2
**Contracts Reviewed:** 10 contracts

---

## Executive Summary

This security audit covers the stYFI protocol, a YFI staking and reward distribution system implemented in Vyper 0.4.2. The protocol consists of multiple interconnected contracts managing staked YFI tokens, liquid locker functionality, voting escrow migrations, and reward distribution across various components.

### Overall Risk Assessment: **LOW-MEDIUM**

The codebase demonstrates strong security practices including:
- Two-step management transfer pattern
- Proper access control on privileged functions
- Safe ERC20 handling with `default_return_value=True`
- Consistent use of immutables for critical addresses

However, several vulnerabilities and areas of concern were identified that require attention.

---

## Findings Summary

| Severity | Count |
|----------|-------|
| HIGH | 3 |
| MEDIUM | 5 |
| LOW | 6 |
| INFORMATIONAL | 8 |

---

## High Findings

### [H-01] Reentrancy Risk in Hook Callbacks

**Severity:** HIGH
**Files:**
- `contracts/StakedYFI.vy` - Lines 350, 365, 385
- `contracts/DelegatedStakedYFI.vy` - Lines 348, 364, 385
- `contracts/LiquidLockerDepositor.vy` - Lines 329, 149

**Description:** The contracts make external calls to hook contracts (`on_transfer`, `on_stake`, `on_unstake`) after state changes but before emitting events. While Vyper provides some reentrancy protection, the hook contracts are external and could be malicious if management sets an attacker-controlled address.

**Vulnerable Code (StakedYFI.vy):**
```vyper
# Line 340-352 - _transfer function
@internal
def _transfer(_from: address, _to: address, _value: uint256):
    assert _to != empty(address) and _to != self

    self.balanceOf[_from] -= _value
    self.balanceOf[_to] += _value

    extcall self.hooks.on_transfer(msg.sender, _from, _to, _value)  # Line 350 - External call

    log Transfer(sender=_from, receiver=_to, value=_value)  # Line 352

# Line 354-368 - _stake function
@internal
def _stake(_receiver: address, _value: uint256):
    # ... state changes ...
    assert extcall IERC20(asset).transferFrom(msg.sender, self, _value, default_return_value=True)  # Line 364
    extcall self.hooks.on_stake(msg.sender, _receiver, _value)  # Line 365 - External call
    # events after

# Line 370-387 - _unstake function
@internal
def _unstake(_owner: address, _value: uint256):
    # ... state changes ...
    extcall self.hooks.on_unstake(_owner, _value)  # Line 385 - External call
    # events after
```

**Impact:** If management is compromised or sets a malicious hook address, the hook could reenter the contract or perform unexpected operations. The hooks have full control over the reward distribution logic through StakingRewardDistributor.

**Recommendation:**
1. Consider using a reentrancy guard on state-modifying functions
2. Emit events before external calls
3. Document the trust assumptions around hook contracts clearly

---

### [H-02] 32-bit Timestamp Limitation in _pack Function

**Severity:** HIGH
**Files:**
- `contracts/StakedYFI.vy` - Lines 73, 475-480
- `contracts/DelegatedStakedYFI.vy` - Lines 73, 442-447
- `contracts/LiquidLockerDepositor.vy` - Lines 73, 387-392
- `contracts/StakingRewardDistributor.vy` - Lines 116, 548-553

**Description:** The `_pack` function stores timestamps using only 32 bits (`SMALL_MASK = 2**32 - 1`). This limits timestamps to values up to 4,294,967,295 (approximately year 2106).

**Vulnerable Code (StakedYFI.vy):**
```vyper
# Line 73
SMALL_MASK: constant(uint256) = 2**32 - 1

# Lines 475-480
@internal
@pure
def _pack(_a: uint256, _b: uint256, _c: uint256) -> uint256:
    """
    @notice Pack a small value and two big values into a single storage slot
    """
    assert _a <= SMALL_MASK and _b <= BIG_MASK and _c <= BIG_MASK  # Line 479
    return (_a << 224) | (_b << 112) | _c  # Line 480
```

**Impact:** The contract will cease to function after the year 2106 due to timestamp overflow. While this is a long-term issue, for a financial protocol intended to operate indefinitely, this is a design limitation.

**Recommendation:** Document this limitation clearly or consider using 40-bit timestamps (good until year 36812) by adjusting the bit packing scheme.

---

### [H-03] Potential Underflow in LiquidLockerRedemption.exchange()

**Severity:** HIGH
**File:** `contracts/LiquidLockerRedemption.vy`
**Line:** 160

**Description:** The `exchange()` function decrements `self.used[_idx]` without explicitly checking if sufficient balance exists first.

**Vulnerable Code:**
```vyper
# Lines 148-171
@external
def exchange(_idx: uint256, _shares: uint256) -> uint256:
    """
    @notice Exchange YFI for a liquid locker token
    """
    assert self.enabled[_idx]
    epoch: uint256 = self._epoch()
    assert epoch < lock

    self.used[_idx] -= _shares  # Line 160 - Potential underflow

    recipient: address = self.yfi_recipient
    if recipient == empty(address):
        recipient = self

    assets: uint256 = _shares * self.scales[_idx]

    assert extcall yfi.transferFrom(msg.sender, recipient, _shares, default_return_value=True)
    assert extcall self.tokens[_idx].transfer(msg.sender, assets, default_return_value=True)
    log Exchange(token=self.tokens[_idx].address, amount=_shares)
    return assets
```

**Impact:** While Vyper 0.4.x has safe math by default (this would revert), an attacker could grief users by front-running exchanges. If someone tries to exchange more shares than `used[_idx]`, the transaction reverts, potentially blocking legitimate operations.

**Recommendation:** Add explicit check with a clear error: `assert self.used[_idx] >= _shares, "Insufficient used capacity"`

---

## Medium Findings

### [M-01] Missing Zero Address Check in Constructor

**Severity:** MEDIUM
**Files:**
- `contracts/RewardDistributor.vy` - Lines 70-81
- `contracts/VotingEscrowRewardDistributor.vy` - Lines 123-140
- `contracts/StakingRewardDistributor.vy` - Lines 121-138
- `contracts/RewardClaimer.vy` - Lines 44-50

**Description:** The constructors do not validate that the `_token` parameter is not the zero address.

**Vulnerable Code (RewardDistributor.vy):**
```vyper
# Lines 70-81
@deploy
def __init__(_genesis: uint256, _token: address):
    """
    @notice Constructor
    @param _genesis Genesis timestamp
    @param _token The address of the reward token
    """
    genesis = _genesis
    token = IERC20(_token)  # Line 78 - No zero address check

    self.management = msg.sender
    self.linked_components[COMPONENTS_SENTINEL] = ComponentData(epoch=0, next=COMPONENTS_SENTINEL)
```

**Impact:** Deploying with a zero address token would create a non-functional contract that cannot be fixed since `token` is immutable.

**Recommendation:** Add validation: `assert _token != empty(address)`

---

### [M-02] Unbounded Loop in _sync Functions

**Severity:** MEDIUM
**Files:**
- `contracts/RewardDistributor.vy` - Lines 235, 245, 252
- `contracts/VotingEscrowRewardDistributor.vy` - Lines 407, 417, 434, 442, 479

**Description:** The `_sync` functions use fixed iteration limits (32 epochs), but if the contract falls behind by more than 32 epochs, full synchronization requires multiple transactions.

**Vulnerable Code (RewardDistributor.vy):**
```vyper
# Lines 235-282
@internal
def _sync(_current: uint256) -> bool:
    """
    @notice Finalize weights and rewards for completed epochs in order
    """
    epoch: uint256 = self.last_epoch

    if epoch == _current:
        return True

    pull: IPull = self.pull
    for i: uint256 in range(32):  # Line 245 - Fixed 32 epoch limit
        if epoch == _current:
            break

        # calculate sum of weights of all components
        total_weight: uint256 = 0
        component: address = COMPONENTS_SENTINEL
        for j: uint256 in range(MAX_NUM_COMPONENTS):  # Line 252 - Inner loop
            component = self.linked_components[component].next
            if component == COMPONENTS_SENTINEL:
                break
            # ...
```

**Impact:** If the protocol is inactive for an extended period (more than 32 epochs = ~448 days), syncing requires multiple transactions. This could be expensive and create a temporary DOS situation.

**Recommendation:** Consider adding a permissioned force-sync function that can process more epochs, or document this limitation.

---

### [M-03] Centralization Risk in Management Functions

**Severity:** MEDIUM
**Files:** All contracts

**Description:** The management address has significant control over the protocol:

| Contract | Management Powers |
|----------|-------------------|
| StakedYFI.vy:305-314 | Can set hook contracts |
| RewardDistributor.vy:163-184 | Can add/remove reward components |
| StakingRewardDistributor.vy:343-354 | Can set weight scales affecting rewards |
| VotingEscrowRewardDistributor.vy:316-327 | Can modify weight scale |

**Impact:** A compromised or malicious management account could:
1. Set malicious hooks to steal funds
2. Modify reward weights to favor specific addresses
3. Add malicious components to drain rewards

**Recommendation:**
1. Implement a timelock for sensitive operations
2. Consider multi-sig requirements for management
3. Add upper/lower bounds on configurable parameters

---

### [M-04] ERC4626 Deviation - previewWithdraw Returns Incorrect Value

**Severity:** MEDIUM
**File:** `contracts/LiquidLockerDepositor.vy`
**Lines:** 259-266

**Description:** The `previewWithdraw` function returns the input `_assets` directly instead of calculating the equivalent shares.

**Vulnerable Code:**
```vyper
# Lines 259-266
@view
@external
def previewWithdraw(_assets: uint256) -> uint256:
    """
    @notice Preview a withdrawal
    @param _assets Amount of assets to be withdrawn
    @return Equivalent amount of shares to be burned
    """
    return _assets  # Should return _assets // scale
```

**Impact:** This violates the ERC4626 specification, which states that `previewWithdraw` should return the number of shares required to withdraw the given assets. This could cause integration issues with other protocols relying on ERC4626 compliance.

**Recommendation:** Return `_assets // scale` to match the actual behavior of `withdraw()` at line 163.

---

### [M-05] Reward Loss Due to Precision in Weight Calculations

**Severity:** MEDIUM
**File:** `contracts/StakingRewardDistributor.vy`
**Lines:** 458-461

**Description:** When incrementing weight with small amounts, the time-weighted calculation can lose precision.

**Vulnerable Code:**
```vyper
# Lines 457-462
if _increment == INCREMENT:
    if time > 0:
        time = min(block.timestamp - time, RAMP_LENGTH)
    # amount-weighted average time
    time = block.timestamp - (weight * time) // (weight + _amount)  # Line 461
    weight += _amount
```

**Impact:** Small deposits could result in slightly incorrect time tracking, affecting reward calculations over time. The cumulative effect could lead to minor reward discrepancies.

**Recommendation:** Use higher precision intermediate calculations or document the minimum recommended deposit amount.

---

## Low Findings

### [L-01] Missing Event Emission Documentation in set_hooks

**Severity:** LOW
**File:** `contracts/LiquidLockerDepositor.vy`
**Lines:** 288-293

**Description:** The `set_hooks` function lacks documentation unlike other management functions.

**Code:**
```vyper
# Lines 288-293
@external
def set_hooks(_hooks: address):
    assert msg.sender == self.management

    self.hooks = IHooks(_hooks)
    log SetHooks(hooks=_hooks)
```

**Recommendation:** Add NatSpec documentation consistent with other management functions.

---

### [L-02] No Validation on Weight Scale Bounds

**Severity:** LOW
**Files:**
- `contracts/StakingRewardDistributor.vy` - Lines 343-354
- `contracts/VotingEscrowRewardDistributor.vy` - Lines 316-327

**Description:** The `set_weight_scale` functions only check that values are non-zero but allow extreme ratios.

**Code (StakingRewardDistributor.vy):**
```vyper
# Lines 342-354
@external
def set_weight_scale(_numerator: uint256, _denominator: uint256):
    """
    @notice Set scale by which the total weight is multiplied
    """
    assert msg.sender == self.management
    assert _numerator > 0 and _denominator > 0  # Line 351 - Only zero check

    self.weight_scale = Scale(numerator=_numerator, denominator=_denominator)
    log SetWeightScale(numerator=_numerator, denominator=_denominator)
```

**Impact:** Management could set extreme weight scales that effectively disable or grossly inflate rewards for specific components.

**Recommendation:** Add reasonable bounds on the scale ratio (e.g., `numerator / denominator <= 100`).

---

### [L-03] RewardClaimer.claim() Loop Pattern

**Severity:** LOW
**File:** `contracts/RewardClaimer.vy`
**Lines:** 52-67

**Description:** The loop in `claim()` uses a pattern that may be confusing.

**Code:**
```vyper
# Lines 52-67
@external
def claim(_recipient: address = msg.sender) -> uint256:
    """
    @notice Claim rewards from all components
    """
    amount: uint256 = 0
    for i: uint256 in range(self.num_components, bound=MAX_NUM_COMPONENTS):  # Line 60
        amount += extcall IComponent(self.components[i]).claim(msg.sender)

    if amount > 0:
        assert extcall token.transfer(_recipient, amount, default_return_value=True)
        log Claim(account=msg.sender, rewards=amount)

    return amount
```

**Impact:** This appears to be correct Vyper 0.4.x syntax with `bound=`, but the pattern where `range(n, bound=MAX)` iterates from 0 to n-1 could be misread.

**Recommendation:** Add a comment clarifying this behavior.

---

### [L-04] Unsafe Epoch Calculation with unsafe_div

**Severity:** LOW
**Files:**
- `contracts/RewardDistributor.vy` - Lines 230-232
- `contracts/VotingEscrowRewardDistributor.vy` - Lines 402-404
- `contracts/StakingRewardDistributor.vy` - Lines 413-415
- `contracts/LiquidLockerRedemption.vy` - Lines 264-266

**Description:** The epoch calculations use `unsafe_div`.

**Code (RewardDistributor.vy):**
```vyper
# Lines 230-232
@internal
@view
def _epoch() -> uint256:
    return unsafe_div(block.timestamp - genesis, EPOCH_LENGTH)
```

**Impact:** If `block.timestamp < genesis`, this would cause an underflow before the division. However, the genesis is typically set at deployment time, and once passed, this is safe.

**Recommendation:** Add documentation that functions should not be called before genesis, or add a check.

---

### [L-05] Inconsistent Handling of Zero Amounts

**Severity:** LOW
**Files:** Multiple contracts

**Description:** Some functions check for zero amounts before processing while others don't.

**Examples:**
```vyper
# StakedYFI.vy Line 378 - Has check
if _value > 0:
    # process stream

# StakedYFI.vy Line 114 - Check for optimization
if _value > 0:
    allowance: uint256 = self.allowance[_from][msg.sender]
```

**Impact:** Inconsistent behavior could lead to unexpected state changes or gas waste.

**Recommendation:** Standardize zero-amount handling across all functions.

---

### [L-06] VotingEscrowSnapshot Uses Direct Management Transfer

**Severity:** LOW
**File:** `contracts/VotingEscrowSnapshot.vy`
**Lines:** 82-90

**Description:** Unlike other contracts, VotingEscrowSnapshot uses direct management transfer without a two-step process.

**Code:**
```vyper
# Lines 81-90
@external
def set_management(_management: address):
    """
    @notice Set the new management address
    @param _management New management address
    """
    assert msg.sender == self.management

    self.management = _management  # Line 89 - Direct transfer
    log SetManagement(management=_management)
```

**Impact:** Accidental transfer to wrong address would be irrecoverable.

**Recommendation:** Use the two-step pattern consistent with other contracts (set_management + accept_management).

---

## Informational Findings

### [I-01] Gas Optimization - Storage Reads in Loops

**File:** `contracts/RewardDistributor.vy`
**Lines:** 252-259

**Description:** Within the inner loop, `self.linked_components[component].next` is read from storage on each iteration.

**Recommendation:** The pragma `optimize gas` should handle this, but consider caching in a local variable if needed.

---

### [I-02] Consistent Use of Immutables (Positive)

**Observation:** The codebase correctly uses immutables for values that don't change after deployment (genesis, token addresses, etc.). This is a positive security pattern.

**Examples:**
- `contracts/RewardDistributor.vy:25-26` - `genesis`, `token`
- `contracts/StakedYFI.vy:27` - `asset`
- `contracts/LiquidLockerRedemption.vy:15-17` - `genesis`, `yfi`, `lock`

---

### [I-03] Two-Step Management Transfer (Positive)

**Observation:** All contracts (except VotingEscrowSnapshot) implement a secure two-step management transfer pattern.

**Example (StakedYFI.vy lines 316-338):**
```vyper
@external
def set_management(_management: address):
    assert msg.sender == self.management
    self.pending_management = _management
    log PendingManagement(management=_management)

@external
def accept_management():
    assert msg.sender == self.pending_management
    self.pending_management = empty(address)
    self.management = msg.sender
    log SetManagement(management=msg.sender)
```

---

### [I-04] Safe ERC20 Handling (Positive)

**Observation:** All ERC20 interactions use `default_return_value=True` to handle non-standard tokens.

**Examples:**
- `contracts/StakedYFI.vy:364` - `transferFrom`
- `contracts/StakedYFI.vy:461` - `transfer`
- `contracts/RewardDistributor.vy:125, 147, 266` - Various transfers

---

### [I-05] Missing Transfer Functions in LiquidLockerDepositor

**File:** `contracts/LiquidLockerDepositor.vy`

**Description:** The contract implements ERC4626 but intentionally omits `transfer` and `transferFrom` functions, making the tokens non-transferable. This is documented in the contract header (lines 4-14).

**Recommendation:** Consider implementing these functions to revert with a clear error message for better UX.

---

### [I-06] Hardcoded Epoch Length

**Files:** All contracts

**Description:** `EPOCH_LENGTH` is hardcoded as `14 * 24 * 60 * 60` (14 days) across all contracts.

**Examples:**
- `contracts/RewardDistributor.vy:68`
- `contracts/StakedYFI.vy:75`
- `contracts/VotingEscrowRewardDistributor.vy:119`

**Note:** This is acceptable for the current design but should be documented.

---

### [I-07] Constructor Missing Management Initialization

**File:** `contracts/RewardClaimer.vy`
**Lines:** 44-50

**Description:** The constructor doesn't initialize `self.management`, leaving it as the zero address.

**Code:**
```vyper
@deploy
def __init__(_token: address):
    """
    @notice Constructor
    @param _token Reward token address
    """
    token = IERC20(_token)
    # Missing: self.management = msg.sender
```

**Impact:** Management functions will be inaccessible until `accept_management` is called, but there's no `pending_management` set either.

**Recommendation:** Add `self.management = msg.sender` to constructor.

---

### [I-08] Missing Interface Documentation

**Files:** Multiple contracts

**Description:** While contracts declare `implements:` for interfaces, the relationship between contracts and their expected callers could be better documented.

**Recommendation:** Add architecture documentation describing contract relationships and trust assumptions.

---

## Positive Security Patterns Observed

1. **Consistent Access Control:** All privileged functions properly check `msg.sender == self.management`

2. **Safe Math:** Vyper 0.4.x provides safe math by default, preventing overflow/underflow

3. **Immutable Critical Values:** Token addresses, genesis timestamps, and other critical values are immutable

4. **Event Emission:** All state changes emit appropriate events for off-chain monitoring

5. **Two-Step Management Transfer:** Prevents accidental ownership transfer (with one exception)

6. **Safe External Call Pattern:** Uses `default_return_value=True` for ERC20 calls

7. **Linked List with Sentinel:** RewardDistributor uses a sentinel pattern to manage component list safely

8. **Bit Packing:** Efficient storage usage through bit packing in stream data

---

## Recommendations Summary

### High Priority
1. Add reentrancy protection or document trust assumptions for hook contracts
2. Document the 32-bit timestamp limitation
3. Add explicit bounds checking in `LiquidLockerRedemption.exchange()` (line 160)

### Medium Priority
1. Add zero address validation in constructors
2. Document or mitigate unbounded loop limitations
3. Implement timelock for management operations
4. Fix ERC4626 compliance in `previewWithdraw` (LiquidLockerDepositor.vy:266)

### Low Priority
1. Standardize zero-amount handling
2. Add bounds to configurable parameters
3. Update VotingEscrowSnapshot to use two-step management transfer
4. Improve documentation consistency
5. Initialize management in RewardClaimer constructor

---

## Contracts Reviewed

| Contract | Lines | Description |
|----------|-------|-------------|
| VotingEscrowRewardDistributor.vy | 514 | Migrated veYFI position reward distribution |
| StakedYFI.vy | 489 | ERC4626 staking vault |
| LiquidLockerRedemption.vy | 272 | Liquid locker token redemption |
| RewardDistributor.vy | 295 | Epoch-based reward distribution |
| LiquidLockerDepositor.vy | 401 | ERC4626 liquid locker deposit vault |
| StakingRewardDistributor.vy | 562 | Staking-based reward component |
| DelegatedStakedYFI.vy | 456 | Delegated staking wrapper |
| RewardClaimer.vy | 136 | Multi-component reward claiming |
| VotingEscrowSnapshot.vy | 91 | veYFI position snapshots |

---

## Conclusion

The stYFI protocol demonstrates solid security fundamentals with consistent patterns for access control, safe token handling, and state management. The Vyper implementation provides inherent protections against common vulnerabilities like integer overflow.

The centralization risks around management functions should be mitigated through timelocks or multi-sig requirements for production deployment.

The protocol's complex reward distribution mechanism across multiple components requires careful integration testing to ensure economic invariants are maintained under all conditions.
