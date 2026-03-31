# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Team Factory
@author Yearn Finance
@license GNU AGPLv3
@notice Permissionless factory for deploying teams, which are minimal proxies
        pointing to a deployment of the Team contract.
"""

interface IFactory:
    def deployed(_team: address) -> bool: view
implements: IFactory

interface ITeam:
    def setup(_name: String[100], _registry: address, _owner: address): nonpayable

registry: public(immutable(address))
implementation: public(immutable(address))
num_deployments: public(uint256)
deployments: public(HashMap[uint256, address])
deployed: public(HashMap[address, bool])

event Deploy:
    deployer: indexed(address)
    team: indexed(address)
    owner: indexed(address)
    name: String[100]

@deploy
def __init__(_registry: address, _implementation: address):
    """
    @notice Constructor
    @param _registry Registry address
    @param _implementation Team implementation contract address
    """
    registry = _registry
    implementation = _implementation

@external
def deploy(_name: String[100], _owner: address = msg.sender) -> address:
    """
    @notice Deploy a team contract
    @param _name Team name
    @param _owner Team owner. Defaults to caller
    @return Team address
    """
    team: address = create_minimal_proxy_to(implementation)
    extcall ITeam(team).setup(_name, registry, _owner)
    idx: uint256 = self.num_deployments
    self.num_deployments = idx + 1
    self.deployments[idx] = team
    self.deployed[team] = True

    log Deploy(deployer=msg.sender, team=team, owner=_owner, name=_name)
    return team
