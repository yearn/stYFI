from ape import reverts
from pytest import fixture, mark

EPOCH_LENGTH = 14 * 24 * 60 * 60
UNIT = 10**18
PRECISION = 10**30
SCALES = [1, 4, 1]
CAPACITIES = [4 * UNIT, 2 * UNIT, 3 * UNIT]

@fixture
def ll_tokens(project, deployer):
    return [project.MockToken.deploy(sender=deployer) for _ in range(3)]

@fixture
def redemption(chain, project, deployer, yfi, genesis, ll_tokens):
    chain.pending_timestamp = genesis
    return project.LiquidLockerRedemption.deploy(genesis, yfi, 8, ll_tokens, SCALES, sender=deployer)

@mark.parametrize("idx", [0, 1, 2])
def test_redeem(deployer, alice, yfi, ll_tokens, redemption, idx):
    ll_token = ll_tokens[idx]
    scale = SCALES[idx]
    cap = CAPACITIES[idx]

    yfi.mint(redemption, cap, sender=deployer)
    ll_token.mint(alice, UNIT, sender=deployer)
    ll_token.approve(redemption, 2**256 - 1, sender=alice)
    redemption.set_enabled(idx, True, sender=deployer)

    with reverts():
        redemption.redeem(idx, UNIT, sender=alice)

    redemption.set_capacity(idx, cap, sender=deployer)
    redemption.redeem(idx, UNIT, sender=alice)
    assert redemption.used(idx) == UNIT // scale
    assert yfi.balanceOf(alice) == UNIT // scale * 9 // 10

    amt = cap - UNIT // scale
    ll_token.mint(alice, amt * scale + scale, sender=deployer)

    with reverts():
        redemption.redeem(idx, amt * scale + scale, sender=alice)

    redemption.redeem(idx, amt * scale, sender=alice)

@mark.parametrize("idx", [0, 1, 2])
def test_exchange(deployer, alice, yfi, ll_tokens, redemption, idx):
    ll_token = ll_tokens[idx]
    scale = SCALES[idx]
    cap = CAPACITIES[idx]

    yfi.mint(redemption, UNIT, sender=deployer)
    ll_token.mint(alice, UNIT, sender=deployer)
    ll_token.approve(redemption, UNIT, sender=alice)
    redemption.set_enabled(idx, True, sender=deployer)

    redemption.set_capacity(idx, cap, sender=deployer)
    redemption.redeem(idx, UNIT, sender=alice)

    yfi_amt = UNIT // scale * 9 // 10
    
    yfi.approve(redemption, yfi_amt, sender=alice)
    redemption.exchange(idx, yfi_amt, sender=alice)
    assert ll_token.balanceOf(alice) == UNIT * 9 // 10
