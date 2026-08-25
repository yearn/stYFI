from ape import reverts
from pytest import fixture, mark

EPOCH_LENGTH = 14 * 24 * 60 * 60
PROPOSE_COOLDOWN = 24 * 60 * 60
COMPONENTS_SENTINEL = '0x1111111111111111111111111111111111111111'
UNIT = 10**18
SMALL_UNIT = 10**12
WEIGHT_PACKING_SCALE = 10**10
MAX = 2**256 - 1
SCALES = [1, 2, 1]
IPFS_HASH = '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef'

@fixture
def srd(chain, project, deployer, reward, distributor, genesis):
    chain.pending_timestamp = genesis
    srd = project.StakingRewardDistributor.deploy(distributor, reward, sender=deployer)
    distributor.add_component(srd, 4, 1, COMPONENTS_SENTINEL, sender=deployer)
    return srd

@fixture
def old_aggregator(project, deployer):
    return project.MockHooks.deploy(sender=deployer)

@fixture
def old_styfi_middleware(project, deployer, styfi, srd, old_aggregator):
    middleware = project.StakingMiddleware.deploy(styfi, srd, old_aggregator, sender=deployer)
    styfi.set_hooks(middleware, sender=deployer)
    srd.set_depositor(middleware, sender=deployer)
    srd.set_staking(styfi, sender=deployer)
    return middleware

@fixture
def dsrd(project, deployer, reward, srd):
    return project.DelegatedStakingRewardDistributor.deploy(srd, reward, sender=deployer)

@fixture
def styfix(project, deployer, styfi, srd, old_styfi_middleware, dsrd):
    styfix = project.DelegatedStakedYFI.deploy(styfi, sender=deployer)
    styfix.set_hooks(dsrd, sender=deployer)
    srd.set_claimer(dsrd, True, sender=deployer)
    old_styfi_middleware.set_instant_withdrawal(styfix, True, sender=deployer)
    dsrd.set_depositor(styfix, sender=deployer)
    dsrd.set_staking(styfix, sender=deployer)
    dsrd.set_distributor_claim(styfix, sender=deployer)
    return styfix

@fixture
def styfix_middleware(project, deployer, genesis, styfix, dsrd):
    middleware = project.DelegatedStakingMiddleware.deploy(genesis, styfix, dsrd, sender=deployer)
    styfix.set_hooks(middleware, sender=deployer)
    dsrd.set_depositor(middleware, sender=deployer)
    return middleware

@fixture
def lls(project, deployer):
    return [project.MockToken.deploy(sender=deployer) for _ in SCALES]

@fixture
def ll_depositors(project, deployer, lls):
    return [project.LiquidLockerDepositor.deploy(ll, scale, "", "", sender=deployer) for scale, ll in zip(SCALES, lls)]

@fixture
def llrd(project, deployer, reward, distributor, ll_depositors):
    llrd = project.LiquidLockerRewardDistributor.deploy(distributor, reward, 100, ll_depositors, sender=deployer)
    distributor.add_component(llrd, 4, 1, COMPONENTS_SENTINEL, sender=deployer)
    for depositor in ll_depositors:
        depositor.set_capacity(10**20, sender=deployer)
        depositor.set_hooks(llrd, sender=deployer)
    return llrd

@fixture
def veyfi(project, deployer):
    return project.MockVotingEscrow.deploy(sender=deployer)

@fixture
def verd(project, deployer, distributor, reward, veyfi):
    verd = project.VotingEscrowRewardDistributor.deploy(distributor, reward, veyfi, sender=deployer)
    distributor.add_component(verd, 4, 1, COMPONENTS_SENTINEL, sender=deployer)
    return verd

@fixture
def styfi_middleware(project, deployer, styfi, srd, aggregator):
    return project.StakingMiddleware.deploy(styfi, srd, aggregator, sender=deployer)

@fixture
def ll_middlewares(project, deployer, ll_depositors, llrd, aggregator):
    return [project.LiquidLockerMiddleware.deploy(depositor, llrd, aggregator, sender=deployer) for depositor in ll_depositors]

@fixture
def aggregator(chain, project, deployer, genesis, llrd, styfix):
    chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH
    return project.WeightAggregator.deploy(genesis, sender=deployer)

@fixture
def downstream(project, deployer):
    return project.MockHooks.deploy(sender=deployer)

@fixture
def vbrd(project, deployer, reward, distributor, styfi, aggregator, downstream, srd, verd, styfi_middleware, ll_depositors, llrd, ll_middlewares):
    styfi.set_hooks(styfi_middleware, sender=deployer)
    srd.set_depositor(styfi_middleware, sender=deployer)
    aggregator.activate([styfi_middleware] + ll_middlewares, sender=deployer)

    for i in range(len(SCALES)):
        ll_depositors[i].set_hooks(ll_middlewares[i], sender=deployer)
        llrd.set_depositor(ll_depositors[i], ll_middlewares[i], sender=deployer)

    vbrd = project.VoteBoostRewardDistributor.deploy(distributor, reward, 20, sender=deployer)
    vbrd.set_upstream(aggregator, sender=deployer)
    vbrd.set_downstream(downstream, sender=deployer)
    vbrd.set_weight_aggregator(aggregator, sender=deployer)
    vbrd.set_snapshot(verd, sender=deployer)
    vbrd.set_staking(styfi, sender=deployer)
    aggregator.set_downstream(vbrd, sender=deployer)
    distributor.add_component(vbrd, 6, 1, COMPONENTS_SENTINEL, sender=deployer)
    vbrd.activate(sender=deployer)
    return vbrd

@fixture
def measure(project, deployer, genesis, aggregator, styfix_middleware, verd):
    return project.WeightMeasure.deploy(genesis, aggregator, styfix_middleware, verd, sender=deployer)

@fixture
def voting(project, deployer, genesis, vbrd, measure, styfi_middleware):
    voting = project.Voting.deploy(genesis, sender=deployer)
    voting.set_weight_measure(measure, sender=deployer)
    voting.set_hooks(vbrd, sender=deployer)
    voting.set_propose_parameters(10**18, PROPOSE_COOLDOWN, styfi_middleware, sender=deployer)
    vbrd.set_voting(voting, True, sender=deployer)
    return voting

@fixture
def ybc(project, deployer):
    return project.MockYBC.deploy(sender=deployer)

@fixture
def voter(project, deployer, genesis, voting, ybc):
    voter = project.Voter.deploy(genesis, sender=deployer)
    voter.set_ybc(ybc, sender=deployer)
    voting.set_vote_parameters(EPOCH_LENGTH // 2, voter, sender=deployer)
    return voter

def test_propose(deployer, alice, genesis, veyfi, verd, vbrd, voting):
    # proposing updates the proposal counts
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)

    assert vbrd.packed_proposal_epochs(voting, 0) == 0
    for i in range(6):
        assert vbrd.num_proposals(5 + i) == 0
    assert vbrd.num_proposals(11) == 0
    assert voting.propose(IPFS_HASH, b"", sender=alice).return_value == 0
    assert vbrd.packed_proposal_epochs(voting, 0) >> 1 == 5
    for i in range(6):
        assert vbrd.num_proposals(5 + i) == 1
    assert vbrd.num_proposals(11) == 0

def test_propose_sequential(chain, deployer, alice, genesis, veyfi, verd, vbrd, voting):
    # proposing in sequential epochs updates the counts as expected
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)
    
    assert voting.propose(IPFS_HASH, b"", sender=alice).return_value == 0
    chain.pending_timestamp += EPOCH_LENGTH
    assert voting.propose(IPFS_HASH, b"", sender=alice).return_value == 1

    assert vbrd.packed_proposal_epochs(voting, 0) >> 1 == 5
    assert vbrd.packed_proposal_epochs(voting, 1) >> 1 == 6
    assert vbrd.num_proposals(4) == 0
    assert vbrd.num_proposals(5) == 1
    for e in range(6, 11):
        assert vbrd.num_proposals(e) == 2
    assert vbrd.num_proposals(11) == 1
    assert vbrd.num_proposals(12) == 0

def test_propose_duplicate(deployer, alice, vbrd):
    # cant submit proposal more than once
    vbrd.set_voting(alice, True, sender=deployer)
    vbrd.on_propose(0, alice, sender=alice)

    with reverts():
        vbrd.on_propose(0, alice, sender=alice)

def test_retract(deployer, alice, genesis, veyfi, verd, vbrd, voting):
    # proposal retraction updates the counts
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)

    voting.propose(IPFS_HASH, b"", sender=alice)
    voting.retract(0, sender=alice)
    assert vbrd.packed_proposal_epochs(voting, 0) == 0
    for i in range(6):
        assert vbrd.num_proposals(5 + i) == 0

def test_retract_voting(chain, deployer, alice, genesis, veyfi, verd, vbrd, voting):
    # proposal can still be retracted after voting epoch begins
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)

    voting.propose(IPFS_HASH, b"", sender=alice)

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH
    voting.retract(0, sender=alice)
    assert vbrd.packed_proposal_epochs(voting, 0) == 0
    for i in range(6):
        assert vbrd.num_proposals(5 + i) == 0

def test_retract_multiple(deployer, alice, vbrd):
    # cant retract multiple times
    vbrd.set_voting(alice, True, sender=deployer)
    vbrd.on_propose(0, alice, sender=alice)
    vbrd.on_retract(0, sender=alice)

    with reverts():
        vbrd.on_retract(0, sender=alice)

def test_retract_late(chain, deployer, alice, vbrd):
    # cant retract after any votes have been submitted
    vbrd.set_voting(alice, True, sender=deployer)
    vbrd.on_propose(0, alice, sender=alice)
    
    chain.pending_timestamp += EPOCH_LENGTH
    vbrd.on_vote(0, alice, sender=alice)
    with reverts():
        vbrd.on_retract(0, sender=alice)

def r(v):
    return v // 10**10 * 10**10

def test_vote(chain, deployer, alice, bob, genesis, veyfi, verd, vbrd, voting, voter):
    # voting sets weights for 6 epochs
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)
    veyfi.set_locked(bob, UNIT, unlock, sender=deployer)
    verd.set_snapshot(bob, UNIT, 60, unlock, sender=deployer)
    verd.migrate(sender=bob)
    voting.propose(IPFS_HASH, b"", sender=alice)
    assert vbrd.packed_proposal_epochs(voting, 0) == 5 << 1

    for i in range(6):
        assert vbrd.weight(5 + i, alice) == 0
        assert vbrd.weight(5 + i, bob) == 0
        assert vbrd.num_votes(5 + i, alice) == 0
        assert vbrd.num_votes(5 + i, bob) == 0

    with chain.isolate():
        chain.pending_timestamp = genesis + 11 * EPOCH_LENGTH
        for i in range(6):
            assert vbrd.sync_total_weight(5 + i, sender=deployer).return_value == 0

    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH - 48 * 60 * 60
    voter.vote_yea(voting, 0, sender=alice)
    voter.vote_nay(voting, 0, sender=bob)

    assert vbrd.packed_proposal_epochs(voting, 0) == (5 << 1) | 1

    chain.pending_timestamp = genesis + 12 * EPOCH_LENGTH
    slope = UNIT // 104
    pwa = UNIT + 46 * slope
    pwb = UNIT + 56 * slope
    
    for e in range(5, 11):
        pwa -= slope
        pwb -= slope
        wa = vbrd.weight(e, alice)
        wb = vbrd.weight(e, bob)
        assert wa == r(pwa)
        assert wb == r(pwb)
        assert vbrd.num_votes(e, alice) == 1
        assert vbrd.num_votes(e, bob) == 1
        assert vbrd.sync_total_weight(e, sender=deployer).return_value == wa + wb
    assert vbrd.weight(11, alice) == 0
    assert vbrd.weight(11, bob) == 0
    assert vbrd.sync_total_weight(11, sender=deployer).return_value == 0
    assert vbrd.num_votes(11, alice) == 0
    assert vbrd.num_votes(11, bob) == 0

def test_vote_components(chain, deployer, alice, genesis, yfi, styfi, lls, ll_depositors, veyfi, verd, aggregator, vbrd, voting, voter):
    # voting uses weights from stYFI, llYFI (with decaying boost) and veYFI (with decaying boost)
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, 5 * UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, 5 * UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)

    yfi.mint(alice, UNIT, sender=alice)
    yfi.approve(styfi, UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)

    for i in range(len(SCALES)):
        amt = (i + 2) * SCALES[i] * UNIT
        lls[i].mint(alice, amt, sender=alice)
        lls[i].approve(ll_depositors[i], amt, sender=alice)
        ll_depositors[i].deposit(amt, sender=alice)

    assert aggregator.staked(alice) == 10 * UNIT

    voting.propose(IPFS_HASH, b"", sender=alice)
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH - 48 * 60 * 60
    voter.vote_yea(voting, 0, sender=alice)

    slope = 5 * UNIT // 104
    vw = 46 * slope

    chain.pending_timestamp = genesis + 12 * EPOCH_LENGTH
    for e in range(5, 11):
        vw -= slope
        ew  = 15 * UNIT
        ew += 9 * UNIT * (104 - e) // 104 # llYFI
        ew += vw # veYFI
        w = vbrd.weight(e, alice)
        assert w == r(ew)
        assert vbrd.sync_total_weight(e, sender=deployer).return_value == w

def test_vote_multiple(chain, deployer, alice, bob, genesis, yfi, styfi, lls, ll_depositors, veyfi, verd, vbrd, voting, voter):
    # boost depends on fraction of votes submitted
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, 5 * UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, 5 * UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)
    veyfi.set_locked(bob, 5 * UNIT, unlock, sender=deployer)
    verd.set_snapshot(bob, 5 * UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=bob)

    yfi.mint(alice, UNIT, sender=alice)
    yfi.approve(styfi, UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)

    yfi.mint(bob, UNIT, sender=bob)
    yfi.approve(styfi, UNIT, sender=bob)
    styfi.deposit(UNIT, sender=bob)

    for i in range(len(SCALES)):
        amt = (i + 2) * SCALES[i] * UNIT
        lls[i].mint(alice, amt, sender=alice)
        lls[i].approve(ll_depositors[i], amt, sender=alice)
        ll_depositors[i].deposit(amt, sender=alice)

        lls[i].mint(bob, amt, sender=bob)
        lls[i].approve(ll_depositors[i], amt, sender=bob)
        ll_depositors[i].deposit(amt, sender=bob)

    voting.propose(IPFS_HASH, b"", sender=alice)
    voting.propose(IPFS_HASH, b"", sender=bob)
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH - 48 * 60 * 60
    voter.vote_yea(voting, 0, sender=alice)
    voter.vote_yea(voting, 1, sender=alice)
    voter.vote_yea(voting, 0, sender=bob)

    slope = 5 * UNIT // 104
    vw = 46 * slope

    chain.pending_timestamp = genesis + 12 * EPOCH_LENGTH
    for e in range(5, 11):
        vw -= slope
        ew  = 15 * UNIT
        ew += 9 * UNIT * (104 - e) // 104 # llYFI
        ew += vw # veYFI
        wa = vbrd.weight(e, alice)
        wb = vbrd.weight(e, bob)
        assert wa == r(2 * ew) # 100% participation
        assert wb == r(ew) # 50% participation
        assert vbrd.sync_total_weight(e, sender=deployer).return_value == (wa + wb) // 2

def test_vote_sequential(chain, deployer, alice, bob, genesis, yfi, styfi, lls, ll_depositors, veyfi, verd, vbrd, voting, voter):
    # voting in sequential epochs works as expected
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, 5 * UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, 5 * UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)
    veyfi.set_locked(bob, 5 * UNIT, unlock, sender=deployer)
    verd.set_snapshot(bob, 5 * UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=bob)

    yfi.mint(alice, UNIT, sender=alice)
    yfi.approve(styfi, UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)

    yfi.mint(bob, UNIT, sender=bob)
    yfi.approve(styfi, UNIT, sender=bob)
    styfi.deposit(UNIT, sender=bob)

    for i in range(len(SCALES)):
        amt = (i + 2) * SCALES[i] * UNIT
        lls[i].mint(alice, amt, sender=alice)
        lls[i].approve(ll_depositors[i], amt, sender=alice)
        ll_depositors[i].deposit(amt, sender=alice)

        lls[i].mint(bob, amt, sender=bob)
        lls[i].approve(ll_depositors[i], amt, sender=bob)
        ll_depositors[i].deposit(amt, sender=bob)

    voting.propose(IPFS_HASH, b"", sender=alice)
    voting.propose(IPFS_HASH, b"", sender=bob)
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH - 48 * 60 * 60
    voter.vote_yea(voting, 0, sender=alice)
    voter.vote_yea(voting, 1, sender=alice)
    voter.vote_yea(voting, 0, sender=bob)
    voting.propose(IPFS_HASH, b"", sender=alice)
    chain.pending_timestamp = genesis + 7 * EPOCH_LENGTH - 48 * 60 * 60
    voter.vote_yea(voting, 2, sender=alice)
    voter.vote_yea(voting, 2, sender=bob)

    slope = 5 * UNIT // 104
    vw = 46 * slope

    chain.pending_timestamp = genesis + 13 * EPOCH_LENGTH

    for e in range(5, 12):
        vw -= slope
        ew  = 15 * UNIT
        ew += 9 * UNIT * (104 - e) // 104 # llYFI
        ew += vw # veYFI
        wa = vbrd.weight(e, alice)
        wb = vbrd.weight(e, bob)

        if e == 5:
            n = 2
            assert wa == r(2 * ew)
            assert wb == r(ew)
        elif e == 11:
            n = 1
            assert wa == r(ew)
            assert wb == r(ew)
        else:
            n = 3
            assert wa == r(3 * ew)
            assert wb == r(2 * ew)

        assert vbrd.sync_total_weight(e, sender=deployer).return_value == (wa + wb) // n

def test_vote_rollover(chain, deployer, alice, bob, genesis, veyfi, verd, vbrd, voting, voter):
    # voting sets counts for the next 6 epochs, even if we roll over to the next storage slot
    unlock = genesis + 100 * EPOCH_LENGTH
    veyfi.set_locked(alice, UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, UNIT, 100, unlock, sender=deployer)
    verd.migrate(sender=alice)
    veyfi.set_locked(bob, UNIT, unlock, sender=deployer)
    verd.set_snapshot(bob, UNIT, 100, unlock, sender=deployer)
    verd.migrate(sender=bob)

    chain.pending_timestamp = genesis + 61 * EPOCH_LENGTH
    voting.propose(IPFS_HASH, b"", sender=alice)
    voting.propose(IPFS_HASH, b"", sender=bob)

    for e in range(62, 68):
        assert vbrd.num_votes(e, alice) == 0
        assert vbrd.num_votes(e, bob) == 0

    chain.pending_timestamp = genesis + 63 * EPOCH_LENGTH - 48 * 60 * 60
    voter.vote_yea(voting, 0, sender=alice)
    voter.vote_yea(voting, 1, sender=alice)
    voter.vote_nay(voting, 0, sender=bob)

    for e in range(62, 68):
        assert vbrd.num_votes(e, alice) == 2
        assert vbrd.num_votes(e, bob) == 1

def test_ll_unlock(chain, deployer, alice, genesis, yfi, styfi, lls, ll_depositors, veyfi, verd, aggregator, vbrd, voting, voter):
    # weights take into account when llYFI unlocks
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, 5 * UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, 5 * UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)

    yfi.mint(alice, UNIT, sender=alice)
    yfi.approve(styfi, UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)

    for i in range(len(SCALES)):
        amt = (i + 2) * SCALES[i] * UNIT
        lls[i].mint(alice, amt, sender=alice)
        lls[i].approve(ll_depositors[i], amt, sender=alice)
        ll_depositors[i].deposit(amt, sender=alice)

    chain.pending_timestamp = genesis + 16 * EPOCH_LENGTH
    voting.propose(IPFS_HASH, b"", sender=alice)
    chain.pending_timestamp = genesis + 18 * EPOCH_LENGTH - 48 * 60 * 60
    voter.vote_yea(voting, 0, sender=alice)

    slope = 5 * UNIT // 104
    vw = 34 * slope

    chain.pending_timestamp = genesis + 24 * EPOCH_LENGTH
    for e in range(17, 23):
        vw -= slope
        ew  = 15 * UNIT
        if e < 20:
            ew += 9 * UNIT * (104 - e) // 104 # llYFI
        else:
            ew -= 9 * UNIT
        ew += vw # veYFI
        w = vbrd.weight(e, alice)
        assert w == r(ew)
        assert vbrd.sync_total_weight(e, sender=deployer).return_value == w

def test_ve_unlock(chain, deployer, alice, genesis, yfi, styfi, lls, ll_depositors, veyfi, verd, aggregator, vbrd, voting, voter):
    # weights take into account when veYFI unlocks
    unlock = genesis + 9 * EPOCH_LENGTH
    veyfi.set_locked(alice, 5 * UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, 5 * UNIT, 9, unlock, sender=deployer)
    verd.migrate(sender=alice)

    yfi.mint(alice, UNIT, sender=alice)
    yfi.approve(styfi, UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)

    for i in range(len(SCALES)):
        amt = (i + 2) * SCALES[i] * UNIT
        lls[i].mint(alice, amt, sender=alice)
        lls[i].approve(ll_depositors[i], amt, sender=alice)
        ll_depositors[i].deposit(amt, sender=alice)

    voting.propose(IPFS_HASH, b"", sender=alice)
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH - 48 * 60 * 60
    voter.vote_yea(voting, 0, sender=alice)

    slope = 5 * UNIT // 104
    vw = 5 * slope

    chain.pending_timestamp = genesis + 12 * EPOCH_LENGTH
    for e in range(5, 11):
        vw -= slope
        ew  = 15 * UNIT
        ew += 9 * UNIT * (104 - e) // 104 # llYFI

        if e < 9:
            ew += vw # veYFI
        else:
            ew -= 5 * UNIT
        w = vbrd.weight(e, alice)
        assert w == r(ew)
        assert vbrd.sync_total_weight(e, sender=deployer).return_value == w

def test_stake(chain, deployer, alice, genesis, yfi, styfi, lls, ll_depositors, veyfi, verd, vbrd, aggregator, voting, voter):
    # staking updates the weights
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, 5 * UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, 5 * UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)

    yfi.mint(alice, 2 * UNIT, sender=alice)
    yfi.approve(styfi, 2 * UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)

    for i in range(len(SCALES)):
        amt = (i + 2) * SCALES[i] * UNIT
        lls[i].mint(alice, amt, sender=alice)
        lls[i].approve(ll_depositors[i], amt, sender=alice)
        ll_depositors[i].deposit(amt, sender=alice)

    voting.propose(IPFS_HASH, b"", sender=alice)
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH - 48 * 60 * 60
    voter.vote_yea(voting, 0, sender=alice)

    # stake
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH
    styfi.deposit(UNIT, sender=alice)
    assert aggregator.staked(alice) == 11 * UNIT

    slope = 5 * UNIT // 104
    vw = 46 * slope

    chain.pending_timestamp = genesis + 12 * EPOCH_LENGTH
    for e in range(5, 11):
        vw -= slope
        ew  = 15 * UNIT
        if e > 5:
            ew += UNIT
        ew += 9 * UNIT * (104 - e) // 104 # llYFI
        ew += vw # veYFI
        w = vbrd.weight(e, alice)
        assert w == r(ew)
        assert vbrd.sync_total_weight(e, sender=deployer).return_value == w
    assert vbrd.weight(11, alice) == 0

@mark.parametrize("idx", [0, 1, 2])
def test_stake_ll(chain, deployer, alice, genesis, yfi, styfi, lls, ll_depositors, veyfi, verd, vbrd, aggregator, voting, voter, idx):
    # staking LL updates the weights
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, 5 * UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, 5 * UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)

    yfi.mint(alice, UNIT, sender=alice)
    yfi.approve(styfi, UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)

    for i in range(len(SCALES)):
        amt = (i + 2) * SCALES[i] * UNIT
        lls[i].mint(alice, amt, sender=alice)
        lls[i].approve(ll_depositors[i], amt, sender=alice)
        ll_depositors[i].deposit(amt, sender=alice)

    voting.propose(IPFS_HASH, b"", sender=alice)
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH - 48 * 60 * 60
    voter.vote_yea(voting, 0, sender=alice)

    # stake
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH
    amt = SCALES[idx] * UNIT
    lls[idx].mint(alice, amt, sender=alice)
    lls[idx].approve(ll_depositors[idx], amt, sender=alice)
    tx = ll_depositors[idx].deposit(amt, sender=alice)
    tx.show_trace()
    assert aggregator.staked(alice) == 11 * UNIT

    slope = 5 * UNIT // 104
    vw = 46 * slope

    chain.pending_timestamp = genesis + 12 * EPOCH_LENGTH
    for e in range(5, 11):
        vw -= slope
        ew  = 15 * UNIT
        if e == 5:
            ew += 9 * UNIT * (104 - e) // 104 # llYFI
        else:
            ew += UNIT
            ew += 10 * UNIT * (104 - e) // 104 # llYFI
        ew += vw # veYFI
        w = vbrd.weight(e, alice)
        assert w == r(ew)
        assert vbrd.sync_total_weight(e, sender=deployer).return_value == w
    assert vbrd.weight(11, alice) == 0

def test_unstake(chain, deployer, alice, genesis, yfi, styfi, lls, ll_depositors, veyfi, verd, vbrd, aggregator, voting, voter):
    # unstaking updates the weights
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, 5 * UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, 5 * UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)

    yfi.mint(alice, UNIT, sender=alice)
    yfi.approve(styfi, UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)

    for i in range(len(SCALES)):
        amt = (i + 2) * SCALES[i] * UNIT
        lls[i].mint(alice, amt, sender=alice)
        lls[i].approve(ll_depositors[i], amt, sender=alice)
        ll_depositors[i].deposit(amt, sender=alice)

    voting.propose(IPFS_HASH, b"", sender=alice)
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH - 48 * 60 * 60
    voter.vote_yea(voting, 0, sender=alice)

    # unstake
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH
    styfi.unstake(UNIT, sender=alice)
    assert aggregator.staked(alice) == 9 * UNIT

    slope = 5 * UNIT // 104
    vw = 46 * slope

    chain.pending_timestamp = genesis + 12 * EPOCH_LENGTH
    for e in range(5, 11):
        vw -= slope
        ew  = 15 * UNIT
        if e > 5:
            ew -= UNIT
        ew += 9 * UNIT * (104 - e) // 104 # llYFI
        ew += vw # veYFI
        w = vbrd.weight(e, alice)
        assert w == r(ew)
        assert vbrd.sync_total_weight(e, sender=deployer).return_value == w
    assert vbrd.weight(11, alice) == 0

@mark.parametrize("idx", [0, 1, 2])
def test_unstake_ll(chain, deployer, alice, genesis, yfi, styfi, lls, ll_depositors, veyfi, verd, vbrd, aggregator, voting, voter, idx):
    # unstaking LL updates the weights
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, 5 * UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, 5 * UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)

    yfi.mint(alice, UNIT, sender=alice)
    yfi.approve(styfi, UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)

    for i in range(len(SCALES)):
        amt = (i + 2) * SCALES[i] * UNIT
        lls[i].mint(alice, amt, sender=alice)
        lls[i].approve(ll_depositors[i], amt, sender=alice)
        ll_depositors[i].deposit(amt, sender=alice)

    voting.propose(IPFS_HASH, b"", sender=alice)
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH - 48 * 60 * 60
    voter.vote_yea(voting, 0, sender=alice)

    # unstake
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH
    ll_depositors[idx].unstake(UNIT, sender=alice)
    assert aggregator.staked(alice) == 9 * UNIT

    slope = 5 * UNIT // 104
    vw = 46 * slope

    chain.pending_timestamp = genesis + 12 * EPOCH_LENGTH
    for e in range(5, 11):
        vw -= slope
        ew  = 15 * UNIT
        if e == 5:
            ew += 9 * UNIT * (104 - e) // 104 # llYFI
        else:
            ew -= UNIT
            ew += 8 * UNIT * (104 - e) // 104 # llYFI
        ew += vw # veYFI
        w = vbrd.weight(e, alice)
        assert w == r(ew)
        assert vbrd.sync_total_weight(e, sender=deployer).return_value == w
    assert vbrd.weight(11, alice) == 0

def test_transfer(chain, deployer, alice, bob, genesis, yfi, styfi, lls, ll_depositors, veyfi, verd, vbrd, voting, voter):
    # transfering updates the weights
    unlock = genesis + 50 * EPOCH_LENGTH
    veyfi.set_locked(alice, 5 * UNIT, unlock, sender=deployer)
    verd.set_snapshot(alice, 5 * UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=alice)
    veyfi.set_locked(bob, 5 * UNIT, unlock, sender=deployer)
    verd.set_snapshot(bob, 5 * UNIT, 50, unlock, sender=deployer)
    verd.migrate(sender=bob)

    yfi.mint(alice, UNIT, sender=alice)
    yfi.approve(styfi, UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)

    yfi.mint(bob, UNIT, sender=bob)
    yfi.approve(styfi, UNIT, sender=bob)
    styfi.deposit(UNIT, sender=bob)

    for i in range(len(SCALES)):
        amt = (i + 2) * SCALES[i] * UNIT
        lls[i].mint(alice, amt, sender=alice)
        lls[i].approve(ll_depositors[i], amt, sender=alice)
        ll_depositors[i].deposit(amt, sender=alice)

        lls[i].mint(bob, amt, sender=bob)
        lls[i].approve(ll_depositors[i], amt, sender=bob)
        ll_depositors[i].deposit(amt, sender=bob)

    voting.propose(IPFS_HASH, b"", sender=alice)
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH - 48 * 60 * 60
    voter.vote_yea(voting, 0, sender=alice)
    voter.vote_yea(voting, 0, sender=bob)

    # unstake
    chain.pending_timestamp = genesis + 6 * EPOCH_LENGTH
    styfi.transfer(bob, UNIT, sender=alice)

    slope = 5 * UNIT // 104
    vw = 46 * slope

    chain.pending_timestamp = genesis + 12 * EPOCH_LENGTH

    for e in range(5, 11):
        vw -= slope
        ew  = 15 * UNIT
        ew += 9 * UNIT * (104 - e) // 104 # llYFI
        ew += vw # veYFI
        wa = vbrd.weight(e, alice)
        wb = vbrd.weight(e, bob)
        if e == 5:
            assert wa == r(ew)
            assert wb == r(ew)
        else:
            assert wa == r(ew - UNIT)
            assert wb == r(ew + UNIT)
        assert vbrd.sync_total_weight(e, sender=deployer).return_value == wa + wb
    assert vbrd.weight(11, alice) == 0
    assert vbrd.weight(11, bob) == 0

def test_claim(chain, project, deployer, alice, bob, genesis, reward, distributor, yfi, styfi, styfi_middleware, srd, voting, voter, vbrd):
    # rewards can be claimed
    reward.approve(distributor, 6 * UNIT, sender=deployer)
    reward.mint(deployer, 6 * UNIT, sender=deployer)
    distributor.deposit(6, 6 * UNIT, sender=deployer)

    claimer = project.RewardClaimer.deploy(reward, sender=deployer)
    claimer.add_component(srd, sender=deployer)
    claimer.add_component(vbrd, sender=deployer)

    vbrd.set_claimer(alice, True, sender=deployer)
    vbrd.set_claimer(claimer, True, sender=deployer)
    srd.set_claimer(claimer, True, sender=deployer)

    yfi.mint(alice, 2 * SMALL_UNIT, sender=alice)
    yfi.approve(styfi, 2 * SMALL_UNIT, sender=alice)
    styfi.deposit(SMALL_UNIT, sender=alice)
    styfi.deposit(SMALL_UNIT, bob, sender=alice)

    chain.pending_timestamp += EPOCH_LENGTH
    voting.set_propose_parameters(0, PROPOSE_COOLDOWN, styfi_middleware, sender=deployer)
    voting.propose(IPFS_HASH, b"", sender=alice)
    voting.propose(IPFS_HASH, b"", sender=bob)

    chain.pending_timestamp = genesis + 13 * EPOCH_LENGTH // 2
    voter.vote_yea(voting, 0, sender=alice)
    voter.vote_yea(voting, 1, sender=alice)
    voter.vote_yea(voting, 0, sender=bob)

    # epoch rewards: 6
    # weight: (100% * 1 + 50% * 1) * 6 = 9
    # total weight = (3 + 1) * 4 + 9 = 25

    ts = genesis + 15 * EPOCH_LENGTH // 2

    base_amount = 6 * UNIT * 4 // 25 // 2
    boost_amount = 6 * UNIT * 6 // 25 // 2
    with chain.isolate():
        chain.pending_timestamp = ts
        assert vbrd.claim(alice, sender=alice).return_value == boost_amount
        assert reward.balanceOf(alice) == boost_amount

    chain.pending_timestamp = ts
    assert claimer.claim(sender=alice).return_value == base_amount + boost_amount
    chain.pending_timestamp = ts
    assert claimer.claim(sender=bob).return_value == base_amount + boost_amount // 2

def test_claim_defer(chain, project, deployer, alice, bob, genesis, reward, distributor, yfi, styfi, styfi_middleware, srd, voting, voter, vbrd):
    # defer claims if component is not fully synced
    reward.approve(distributor, 6 * UNIT, sender=deployer)
    reward.mint(deployer, 6 * UNIT, sender=deployer)
    distributor.deposit(6, 6 * UNIT, sender=deployer)

    claimer = project.RewardClaimer.deploy(reward, sender=deployer)
    claimer.add_component(srd, sender=deployer)
    claimer.add_component(vbrd, sender=deployer)

    vbrd.set_claimer(alice, True, sender=deployer)
    vbrd.set_claimer(claimer, True, sender=deployer)
    srd.set_claimer(claimer, True, sender=deployer)

    yfi.mint(alice, 2 * SMALL_UNIT, sender=alice)
    yfi.approve(styfi, 2 * SMALL_UNIT, sender=alice)
    styfi.deposit(SMALL_UNIT, sender=alice)
    styfi.deposit(SMALL_UNIT, bob, sender=alice)

    chain.pending_timestamp += EPOCH_LENGTH
    voting.set_propose_parameters(0, PROPOSE_COOLDOWN, styfi_middleware, sender=deployer)
    voting.propose(IPFS_HASH, b"", sender=alice)
    voting.propose(IPFS_HASH, b"", sender=bob)

    chain.pending_timestamp = genesis + 13 * EPOCH_LENGTH // 2
    voter.vote_yea(voting, 0, sender=alice)
    voter.vote_yea(voting, 1, sender=alice)
    voter.vote_yea(voting, 0, sender=bob)

    chain.pending_timestamp = genesis + 10 * EPOCH_LENGTH
    distributor.sync(sender=deployer)

    chain.pending_timestamp = genesis + 40 * EPOCH_LENGTH
    assert vbrd.claim(alice, sender=alice).return_value == 0
    assert vbrd.claim(alice, sender=alice).return_value > 0

def test_reclaim(chain, deployer, alice, bob, genesis, reward, distributor, yfi, styfi, styfi_middleware, voting, voter, vbrd):
    # expired rewards can be reclaimed
    for i in range(6, 9):
        reward.approve(distributor, i * UNIT, sender=deployer)
        reward.mint(deployer, i * UNIT, sender=deployer)
        distributor.deposit(i, i * UNIT, sender=deployer)

    vbrd.set_reward_expiration(2, 1000, deployer, sender=deployer)
    vbrd.set_claimer(alice, True, sender=deployer)

    yfi.mint(alice, 2 * SMALL_UNIT, sender=alice)
    yfi.approve(styfi, 2 * SMALL_UNIT, sender=alice)
    styfi.deposit(SMALL_UNIT, sender=alice)
    styfi.deposit(SMALL_UNIT, bob, sender=alice)

    chain.pending_timestamp += EPOCH_LENGTH
    voting.set_propose_parameters(0, PROPOSE_COOLDOWN, styfi_middleware, sender=deployer)
    voting.propose(IPFS_HASH, b"", sender=alice)
    voting.propose(IPFS_HASH, b"", sender=bob)

    chain.pending_timestamp = genesis + 13 * EPOCH_LENGTH // 2
    voter.vote_yea(voting, 0, sender=alice)
    voter.vote_yea(voting, 1, sender=alice)
    voter.vote_yea(voting, 0, sender=bob)

    ts = genesis + 19 * EPOCH_LENGTH // 2
    boost_amount = UNIT * 6 // 25
    reclaim_amount = 6 * boost_amount // 2

    chain.pending_timestamp = ts
    assert vbrd.reclaim(alice, sender=bob).return_value == (reclaim_amount * 9 // 10, reclaim_amount // 10)
    assert reward.balanceOf(deployer) == reclaim_amount * 9 // 10
    assert reward.balanceOf(bob) == reclaim_amount // 10

    # follow by regular claim
    claim_amount = 6 * boost_amount // 2 + 7 * boost_amount + 8 * boost_amount // 2
    chain.pending_timestamp = ts
    assert vbrd.claim(alice, sender=alice).return_value == claim_amount
    assert reward.balanceOf(alice) == claim_amount

