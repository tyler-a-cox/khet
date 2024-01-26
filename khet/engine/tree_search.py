"""
Create a tree of possible moves and evaluate them
Use minimax algorithm to find the best move
Incorporate alpha-beta pruning to reduce the number of nodes to evaluate
"""
import math
from copy import deepcopy
from khet.engine.evaluation import evaluate_board_simple

def make_move(board, position, direction, rotation):
    """
    Make a move on the board
    """
    new_board = deepcopy(board)
    new_board.move_piece(position, direction, rotation)
    new_board.end_turn()
    return new_board

def alpha_beta_search(board, depth, alpha=-math.inf, beta=math.inf, maximizing_player=True):
    if depth == 0 or board.is_game_over():
        return evaluate_board_simple(board)

    legal_moves = board.get_all_valid_moves(board)

    if maximizing_player:
        max_eval = float('-inf')
        best_move = None
        for move in legal_moves:
            new_board = make_move(board, move)
            eval_score = alpha_beta_search(new_board, depth - 1, alpha, beta, False)
            if eval_score > max_eval:
                max_eval = eval_score
                best_move = move
            alpha = max(alpha, eval_score)
            if beta <= alpha:
                break  # Beta cutoff
        return best_move

    else:
        min_eval = float('inf')
        best_move = None
        for move in legal_moves:
            new_board = make_move(board, move)
            eval_score = alpha_beta_search(new_board, depth - 1, alpha, beta, True)
            if eval_score < min_eval:
                min_eval = eval_score
                best_move = move
            beta = min(beta, eval_score)
            if beta <= alpha:
                break  # Alpha cutoff
        return best_move
    
def get_state_repr(game):
    """
    """
    return "".join([item if item else "." for row in game for item in row])

state_mode = {None: 0.0, 'X': 1.0, 'O': -1.0}

def get_board_repr(game):
    """
    """
    return np.array([state_mode[item] for row in game for item in row])


class MCTS:
    def __init__(self, nnet):
        """
        """
        self.nnet = nnet
        self.Qsa = {}  # stores Q values for state and action
        self.Nsa = {}  # stores times state and action were visited
        self.P = {}  # stores initial policy
        self.Ns = {}  # stores times state was visited
        self.Es = {}  # stores whether state is terminal
        self.Vs = {}  # stores valid moves for state s
        self.visited = set()

    def get_action_prob(self, game, nsims=100):
        """
        """
        for _ in range(nsims):
            self.search(game)

        s = get_state_repr(game)
        counts = [
            self.Nsa[(s, a)] if (s, a) in self.Nsa else 0
            for a in get_all_valid_moves(game)
        ]
        
        counts_sum = np.sum(counts)
        probs = np.array(counts) / counts_sum
        return probs

    def search(self, game, c_puct=1):
        """
        Fix search function
        """
        board = game.board
        bb = get_board_repr(board)
        
        if is_game_over(board):
            return

        s = get_state_repr(board)
        
        if s not in self.Es:
            self.Es[s] = game

        # leaf node
        if s not in self.P:
            _a, _b = self.nnet(bb)
            v = _b.detach().numpy()
            self.P[s] = _a.detach().numpy()
            valids = game.is_move_valid()
            self.P[s] *= valids
            self.P[s] /= self.P[s].sum()
            self.Vs[s] = valids
            self.Ns[s] = 0
            return -v
        
        valids = self.Vs[s]
        current_best, best_action = -float('inf'), -1

        for a in get_all_valid_moves_nums(board):
            if valids[a]:
                if (s, a) in self.Qsa:
                    u = self.Qsa[(s, a)] + c_puct * self.P[s][a] * np.sqrt(self.Ns[s]) / (1 + self.Nsa[(s, a)])
                else:
                    u = c_puct * self.P[s][a] * np.sqrt(self.Ns[s] + 1e-4)

                if u > current_best:
                    current_best = u
                    best_action = a

        a = best_action
        make_move(game, player)
        
        if (s, a) in self.Qsa:
            self.Qsa[(s, a)] = (self.Nsa[(s, a)] * self.Qsa[(s, a)] + v) / (self.Nsa[(s, a)] + 1)
            self.Nsa[(s, a)] += 1
        else:
            self.Qsa[(s, a)] = v
            self.Nsa[(s, a)] = 1

        self.Ns[s] += 1
        return -v