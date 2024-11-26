from dataclasses import dataclass
import torch

from CVRProblemDef import get_random_noneuclidian_problems


@dataclass
class Reset_State:
    depot_node_matrix: torch.Tensor = None
    # (batch,problem+1,problem+1)
    depot_node_demand: torch.Tensor = None
    # shape: (batch, problem+1)


@dataclass
class Step_State:
    BATCH_IDX: torch.Tensor = None
    POMO_IDX: torch.Tensor = None
    # shape: (batch, pomo)
    selected_count: int = None
    load: torch.Tensor = None
    # shape: (batch, pomo)
    current_node: torch.Tensor = None
    # shape: (batch, pomo)
    ninf_mask: torch.Tensor = None
    # shape: (batch, pomo, problem+1)
    finished: torch.Tensor = None
    # shape: (batch, pomo)


class CVRPEnv:
    def __init__(self, **env_params):

        # Const @INIT
        self.env_params = env_params
        self.problem_size = env_params['problem_size']
        self.pomo_size = env_params['pomo_size']

        self.FLAG__use_saved_problems = False
        self.saved_depot_node_matrix = None  # (batch,problem+1,problem+1)
        self.saved_node_demand = None  # (batch,problem)
        self.saved_index = None

        # Const @Load_Problem
        self.batch_size = None
        self.BATCH_IDX = None
        self.POMO_IDX = None
        # IDX.shape: (batch, pomo)
        # self.depot_node_xy = None
        # shape: (batch, problem+1, 2)

        self.depot_node_matrix = None
        # shape: (batch,problem+1,problem+1)
        self.depot_node_demand = None
        # shape: (batch, problem+1)

        # Dynamic-1
        self.selected_count = None
        self.current_node = None
        # shape: (batch, pomo)
        self.selected_node_list = None
        # shape: (batch, pomo, 0~)

        # Dynamic-2
        self.at_the_depot = None
        # shape: (batch, pomo)
        self.load = None
        # shape: (batch, pomo)
        self.visited_ninf_flag = None
        # shape: (batch, pomo, problem+1)
        self.ninf_mask = None
        # shape: (batch, pomo, problem+1)
        self.finished = None
        # shape: (batch, pomo)

        # states to return
        self.reset_state = Reset_State()
        self.step_state = Step_State()

    def use_saved_problems(self, filename, device):
        self.FLAG__use_saved_problems = True

        loaded_dict = torch.load(filename, map_location=device)
        self.saved_depot_node_matrix = loaded_dict['depot_node_matrix']
        self.saved_node_demand = loaded_dict['node_demand']
        self.saved_index = 0

    def load_problems(self, batch_size):
        self.batch_size = batch_size

        depot_node_matrix, node_demand = get_random_noneuclidian_problems(batch_size, self.problem_size)

        self.depot_node_matrix = depot_node_matrix
        depot_demand = torch.zeros(size=(self.batch_size, 1))
        # shape: (batch, 1)
        self.depot_node_demand = torch.cat((depot_demand, node_demand), dim=1)
        # shape: (batch, problem+1)

        self.BATCH_IDX = torch.arange(self.batch_size)[:, None].expand(self.batch_size, self.pomo_size)
        self.POMO_IDX = torch.arange(self.pomo_size)[None, :].expand(self.batch_size, self.pomo_size)

        self.reset_state.depot_node_matrix = self.depot_node_matrix
        self.reset_state.depot_node_demand = self.depot_node_demand

        self.step_state.BATCH_IDX = self.BATCH_IDX
        self.step_state.POMO_IDX = self.POMO_IDX

    def load_problems_manual(self, depot_node_matrix, node_demand):
        self.batch_size = depot_node_matrix.size(0)

        self.depot_node_matrix = depot_node_matrix

        self.BATCH_IDX = torch.arange(self.batch_size)[:, None].expand(self.batch_size, self.pomo_size)
        self.POMO_IDX = torch.arange(self.pomo_size)[None, :].expand(self.batch_size, self.pomo_size)

        depot_demand = torch.zeros(size=(self.batch_size, 1))
        # shape: (batch, 1)
        device = depot_demand.device
        node_demand = node_demand.to(device)
        depot_node_matrix = depot_node_matrix.to(device)

        self.depot_node_demand = torch.cat((depot_demand, node_demand), dim=1)
        # shape: (batch, problem+1)
        self.reset_state.depot_node_matrix = depot_node_matrix
        self.reset_state.depot_node_demand = self.depot_node_demand

        self.step_state.BATCH_IDX = self.BATCH_IDX
        self.step_state.POMO_IDX = self.POMO_IDX

    def reset(self):
        self.selected_count = 0
        self.current_node = None
        # shape: (batch, pomo)
        self.selected_node_list = torch.zeros((self.batch_size, self.pomo_size, 0), dtype=torch.long)
        # shape: (batch, pomo, 0~)

        self.at_the_depot = torch.ones(size=(self.batch_size, self.pomo_size), dtype=torch.bool)
        # shape: (batch, pomo)
        self.load = torch.ones(size=(self.batch_size, self.pomo_size))
        # shape: (batch, pomo)
        self.visited_ninf_flag = torch.zeros(size=(self.batch_size, self.pomo_size, self.problem_size+1))
        # shape: (batch, pomo, problem+1)
        self.ninf_mask = torch.zeros(size=(self.batch_size, self.pomo_size, self.problem_size+1))
        # shape: (batch, pomo, problem+1)
        self.finished = torch.zeros(size=(self.batch_size, self.pomo_size), dtype=torch.bool)
        # shape: (batch, pomo)

        reward = None
        done = False
        return self.reset_state, reward, done

    def pre_step(self):
        self.step_state.selected_count = self.selected_count
        self.step_state.load = self.load
        self.step_state.current_node = self.current_node
        self.step_state.ninf_mask = self.ninf_mask
        self.step_state.finished = self.finished

        reward = None
        done = False
        return self.step_state, reward, done

    def step(self, selected):
        # selected.shape: (batch, pomo)

        # Dynamic-1 choose node+1
        self.selected_count += 1
        self.current_node = selected
        # shape: (batch, pomo)
        self.selected_node_list = torch.cat((self.selected_node_list, self.current_node[:, :, None]), dim=2)
        # shape: (batch, pomo, 0~)

        # Dynamic-2
        self.at_the_depot = (selected == 0)

        demand_list = self.depot_node_demand[:, None, :].expand(self.batch_size, self.pomo_size, -1)
        # shape: (batch, pomo, problem+1)
        gathering_index = selected[:, :, None]
        # shape: (batch, pomo, 1)
        selected_demand = demand_list.gather(dim=2, index=gathering_index).squeeze(dim=2)
        # shape: (batch, pomo)
        self.load -= selected_demand
        self.load[self.at_the_depot] = 1  # refill loaded at the depot  如果回到了仓库，则重新装满车

        self.visited_ninf_flag[self.BATCH_IDX, self.POMO_IDX, selected] = float('-inf')  # 已经被访问的顾客节点设为 负无穷
        # shape: (batch, pomo, problem+1)
        self.visited_ninf_flag[:, :, 0][~self.at_the_depot] = 0  # depot is considered unvisited, unless you are AT the depot

        self.ninf_mask = self.visited_ninf_flag.clone()
        round_error_epsilon = 0.00001
        demand_too_large = self.load[:, :, None] + round_error_epsilon < demand_list
        # shape: (batch, pomo, problem+1)
        self.ninf_mask[demand_too_large] = float('-inf')
        # shape: (batch, pomo, problem+1)

        newly_finished = (self.visited_ninf_flag == float('-inf')).all(dim=2)
        # shape: (batch, pomo)
        self.finished = self.finished + newly_finished
        # shape: (batch, pomo)

        # do not mask depot for finished episode.
        self.ninf_mask[:, :, 0][self.finished] = 0

        # update_step_state
        self.step_state.selected_count = self.selected_count
        self.step_state.load = self.load
        self.step_state.current_node = self.current_node
        self.step_state.ninf_mask = self.ninf_mask
        self.step_state.finished = self.finished

        # returning values
        done = self.finished.all()
        if done:
            # reward = -self._get_travel_distance()  # note the minus sign!
            reward = - self._get_total_distance()
        else:
            reward = None

        return self.step_state, reward, done

    def _get_total_distance(self):

        # eg:[100,20,31] (batch,pomo,selected_list_length)
        selected_list_length = self.selected_node_list.size(-1)

        node_from = self.selected_node_list
        # shape: (batch, pomo, node) node=selected_list_length
        node_to = self.selected_node_list.roll(dims=2, shifts=-1)

        # shape: (batch, pomo, node)
        batch_index = self.BATCH_IDX[:, :, None].expand(self.batch_size, self.pomo_size, selected_list_length)
        # shape: (batch, pomo, node)
        selected_cost = self.depot_node_matrix[batch_index, node_from, node_to]

        # shape: (batch, pomo, node)
        total_distance = selected_cost.sum(2)
        # shape: (batch, pomo)

        return total_distance