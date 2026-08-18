from ape import reverts
from pytest import fixture, mark

EPOCH_LENGTH = 14 * 24 * 60 * 60
PROPOSE_COOLDOWN = 24 * 60 * 60
COMPONENTS_SENTINEL = '0x1111111111111111111111111111111111111111'
UNIT = 10**18
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
    srd.set_claimer(dsrd, True, sender=deployer)
    old_styfi_middleware.set_instant_withdrawal(styfix, True, sender=deployer)
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
def ybc_aggregator(project, deployer, genesis, aggregator, downstream):
    ybc_aggregator = project.YBCWeightAggregator.deploy(genesis, sender=deployer)
    ybc_aggregator.set_weight_aggregator(aggregator, sender=deployer)
    ybc_aggregator.set_downstream(downstream, sender=deployer)
    return ybc_aggregator

@fixture
def vbrd(project, deployer, reward, distributor, styfi, aggregator, srd, verd, styfi_middleware, ll_depositors, llrd, ll_middlewares):
    styfi.set_hooks(styfi_middleware, sender=deployer)
    srd.set_depositor(styfi_middleware, sender=deployer)
    aggregator.activate([styfi_middleware] + ll_middlewares, sender=deployer)

    for i in range(len(SCALES)):
        ll_depositors[i].set_hooks(ll_middlewares[i], sender=deployer)
        llrd.set_depositor(ll_depositors[i], ll_middlewares[i], sender=deployer)

    vbrd = project.VoteBoostRewardDistributor.deploy(distributor, reward, 20, sender=deployer)
    vbrd.set_upstream(aggregator, sender=deployer)
    vbrd.set_weight_aggregator(aggregator, sender=deployer)
    vbrd.set_snapshot(verd, sender=deployer)
    vbrd.set_staking(styfi, sender=deployer)
    aggregator.set_downstream(vbrd, sender=deployer)
    distributor.add_component(vbrd, 6, 1, COMPONENTS_SENTINEL, sender=deployer)
    return vbrd

@fixture
def measure(project, deployer, genesis, aggregator, styfix_middleware, verd):
    return project.WeightMeasure.deploy(genesis, aggregator, styfix_middleware, verd, sender=deployer)

@fixture
def voting(project, deployer, genesis, styfi_middleware, vbrd, measure):
    voting = project.Voting.deploy(genesis, sender=deployer)
    voting.set_weight_measure(measure, sender=deployer)
    voting.set_propose_parameters(0, PROPOSE_COOLDOWN, styfi_middleware, sender=deployer)
    voting.set_hooks(vbrd, sender=deployer)
    vbrd.set_voting(voting, True, sender=deployer)
    return voting

@fixture
def ybc(project, deployer):
    return project.YBC.deploy(sender=deployer)

@fixture
def voter(project, deployer, genesis, styfix, voting, ybc, ybc_aggregator, vbrd):
    voter = project.Voter.deploy(genesis, sender=deployer)
    voter.set_ybc(ybc, sender=deployer)
    voter.set_ybc_weight_aggregator(ybc_aggregator, sender=deployer)
    voter.set_delegated_staking(styfix, sender=deployer)
    voting.set_vote_parameters(EPOCH_LENGTH, voter, sender=deployer)
    ybc.set_hooks(ybc_aggregator, sender=deployer)
    ybc_aggregator.set_upstream_members(ybc, sender=deployer)
    ybc_aggregator.set_upstream_weights(vbrd, sender=deployer)
    vbrd.set_downstream(ybc_aggregator, sender=deployer)
    return voter

def test_vote(chain, alice, bob, yfi, styfi, styfix, ybc, voting, voter):
    # votes can be submitted
    yfi.mint(alice, 3 * UNIT, sender=alice)
    yfi.approve(styfi, 3 * UNIT, sender=alice)
    styfi.deposit(2 * UNIT, sender=alice)
    styfi.deposit(UNIT, bob, sender=alice)
    voting.propose(IPFS_HASH, b"", sender=alice)

    chain.pending_timestamp += EPOCH_LENGTH
    chain.mine()
    assert voting.votes(alice, 0) == (0, 0)
    prop = voting.proposals(0)
    assert prop.votes == 0
    assert prop.yea == 0
    assert voter.vote_yea(voting, 0, sender=alice).return_value == UNIT // 2
    assert voting.votes(alice, 0) == (UNIT // 2, UNIT // 2)
    assert voting.votes(ybc, 0) == (0, 0)
    assert voting.votes(styfix, 0) == (0, 0)
    prop = voting.proposals(0)
    assert prop.votes == UNIT // 2
    assert prop.yea == UNIT // 2
    
    with reverts():
        # cant vote more than once
        voter.vote_yea(voting, 0, sender=alice)

    assert voter.vote_nay(voting, 0, sender=bob).return_value == UNIT // 4
    assert voting.votes(bob, 0) == (UNIT // 4, 0)
    prop = voting.proposals(0)
    assert prop.votes == UNIT * 3 // 4
    assert prop.yea == UNIT // 2

def test_vote_decay(chain, deployer, alice, bob, genesis, yfi, styfi, voting, voter):
    # vote weight decays near the end of the epoch
    yfi.mint(alice, 2 * UNIT, sender=alice)
    yfi.approve(styfi, 2 * UNIT, sender=alice)
    styfi.deposit(UNIT, sender=alice)
    styfi.deposit(UNIT, bob, sender=alice)

    voter.set_decay_length(24 * 60 * 60, sender=deployer)
    voting.propose(IPFS_HASH, b"", sender=alice)

    ts = genesis + 6 * EPOCH_LENGTH - 24 * 60 * 60
    chain.pending_timestamp = ts
    assert voter.vote_yea(voting, 0, sender=alice).return_value == UNIT // 4

    chain.pending_timestamp = ts + 12 * 60 * 60
    assert voter.vote_yea(voting, 0, sender=bob).return_value == UNIT // 8

def test_vote_ybc(chain, deployer, alice, bob, yfi, styfi, styfix, ybc, voting, voter):
    # ybc members also vote for ybc and delegated staking
    yfi.mint(alice, 11 * UNIT, sender=alice)
    yfi.approve(styfi, 7 * UNIT, sender=alice)
    yfi.approve(styfix, 4 * UNIT, sender=alice)
    styfi.deposit(3 * UNIT, sender=alice)
    styfi.deposit(2 * UNIT, bob, sender=alice)
    styfi.deposit(2 * UNIT, ybc, sender=alice)
    styfix.deposit(4 * UNIT, sender=alice)

    ybc.set_operator(deployer, True, sender=deployer)
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=deployer)

    chain.pending_timestamp += 2 * EPOCH_LENGTH
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=deployer)

    chain.pending_timestamp += EPOCH_LENGTH
    voting.propose(IPFS_HASH, b"", sender=alice)
    chain.pending_timestamp += EPOCH_LENGTH
    
    voter.vote_yea(voting, 0, sender=alice)
    assert voting.votes(ybc, 0) == (2 * UNIT, 2 * UNIT)
    assert voting.votes(styfix, 0) == (4 * UNIT, 4 * UNIT)
    prop = voting.proposals(0)
    assert prop.votes == 9 * UNIT # 3 + 2 + 4
    assert prop.yea == 9 * UNIT

    voter.vote_nay(voting, 0, sender=bob)
    assert voting.votes(ybc, 0) == (2 * UNIT, UNIT * 3 // 2)
    assert voting.votes(styfix, 0) == (4 * UNIT, 3 * UNIT)
    prop = voting.proposals(0)
    assert prop.votes == 11 * UNIT # 3 + 2 + 4 + 2
    assert prop.yea == UNIT * 15 // 2 # 3 + 1.5 + 3

def test_vote_ybc_no_delegate(chain, deployer, alice, bob, yfi, styfi, styfix, ybc, voting, voter):
    # ybc members can still vote without delegations
    yfi.mint(alice, 7 * UNIT, sender=alice)
    yfi.approve(styfi, 7 * UNIT, sender=alice)
    styfi.deposit(3 * UNIT, sender=alice)
    styfi.deposit(2 * UNIT, bob, sender=alice)
    styfi.deposit(2 * UNIT, ybc, sender=alice)

    ybc.set_operator(deployer, True, sender=deployer)
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=deployer)

    chain.pending_timestamp += 2 * EPOCH_LENGTH
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=deployer)

    chain.pending_timestamp += EPOCH_LENGTH
    voting.propose(IPFS_HASH, b"", sender=alice)
    chain.pending_timestamp += EPOCH_LENGTH
    
    voter.vote_yea(voting, 0, sender=alice)
    voter.vote_nay(voting, 0, sender=bob)
    assert voting.votes(styfix, 0) == (0, 0)

def test_vote_ybc_no_stake(chain, deployer, alice, bob, yfi, styfi, styfix, ybc, voting, voter):
    # ybc members can still vote without stYFI in the YBC
    yfi.mint(alice, 9 * UNIT, sender=alice)
    yfi.approve(styfi, 5 * UNIT, sender=alice)
    yfi.approve(styfix, 4 * UNIT, sender=alice)
    styfi.deposit(3 * UNIT, sender=alice)
    styfi.deposit(2 * UNIT, bob, sender=alice)
    styfix.deposit(4 * UNIT, sender=alice)

    ybc.set_operator(deployer, True, sender=deployer)
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=deployer)

    chain.pending_timestamp += 2 * EPOCH_LENGTH
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=deployer)

    chain.pending_timestamp += EPOCH_LENGTH
    voting.propose(IPFS_HASH, b"", sender=alice)
    chain.pending_timestamp += EPOCH_LENGTH
    
    voter.vote_yea(voting, 0, sender=alice)
    voter.vote_nay(voting, 0, sender=bob)
    assert voting.votes(ybc, 0) == (0, 0)
