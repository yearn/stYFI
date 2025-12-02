from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60

@fixture
def deployer(accounts):
    return accounts[0]

@fixture
def alice(accounts):
    return accounts[1]

@fixture
def bob(accounts):
    return accounts[2]

@fixture
def charlie(accounts):
    return accounts[3]

@fixture
def reward(project, deployer):
    return project.MockToken.deploy(sender=deployer)

@fixture
def yfi(project, deployer):
    return project.MockToken.deploy(sender=deployer)

@fixture
def styfi(project, deployer, yfi):
    return project.StakedYFI.deploy(yfi, sender=deployer)

@fixture
def distributor(project, chain, deployer, reward):
    genesis = (chain.pending_timestamp // EPOCH_LENGTH + 1) * EPOCH_LENGTH
    return project.RewardDistributor.deploy(genesis, reward, sender=deployer)

@fixture
def genesis(distributor):
    return distributor.genesis()
