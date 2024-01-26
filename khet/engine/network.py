import torch
from torch import nn
import torch.optim as optim

def loss_function(state, outcome, network, pi):
    """
    """
    logits = network(state)
    prob = nn.Softmax(dim=1)(logits[:, :-1])
    vs = logits[:, -1]
    return torch.square(outcome - vs).sum() - torch.sum(pi * torch.log(prob))

class NeuralNetwork(nn.Module):
    def __init__(self):
        """
        """
        super().__init__()
        self.flatten = nn.Flatten()
        self.linear_relu_stack = nn.Sequential(
            nn.Linear(9, 45),
            nn.ReLU(),
            nn.Linear(45, 45),
            nn.ReLU(),
        )

        self.output1 = nn.Sequential(
            nn.Linear(45, 9),
            nn.Softmax(dim=-1)
        )

        self.output2 = nn.Sequential(
            nn.Linear(45, 1),
            nn.Tanh()
        )
        
    def forward(self, input):
        x = self.linear_relu_stack(input)
        return self.output1(x), self.output2(x)

    