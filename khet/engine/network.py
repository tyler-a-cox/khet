import torch
from torch import nn
import torch.optim as optim

def loss_function(prob, value, outcome, pi):
    """
    Loss function for the neural network training

    Parameters
    ----------
    prob : torch.Tensor
        The probability distribution over the possible moves
    value : torch.Tensor
        The value function for the state
    outcome : torch.Tensor
        The outcome of the game
    pi : torch.Tensor
        The probability distribution over the possible moves

    Returns
    -------
    torch.Tensor
        The loss function
    """
    return torch.square(outcome - value).sum() - torch.sum(pi * torch.log(prob))

class NeuralNetwork(nn.Module):
    """
    Neural network for the game of Khet
    """
    def __init__(self):
        """
        """
        super().__init__()
    
        # Define network layers
        # TODO: Make convolutional
        self.linear_relu_stack = nn.Sequential(
            nn.Linear(9, 45),
            nn.ReLU(),
            nn.Linear(45, 45),
            nn.ReLU(),
        )

        # First set of outputs is a probability distribution over the 9 possible
        self.output1 = nn.Sequential(
            nn.Linear(45, 9),
            nn.Softmax(dim=-1)
        )

        # Second set of outputs is a value function for the state
        self.output2 = nn.Sequential(
            nn.Linear(45, 1),
            nn.Tanh()
        )
        
    def forward(self, input):
        """
        Compute the forward pass of the neural network

        Parameters
        ----------
        input : torch.Tensor
            The input to the neural network
        
        Returns
        -------
        torch.Tensor
            The output of the neural network
        """
        # Pass the input through the network
        x = self.linear_relu_stack(input)

        # Return the output
        return self.output1(x), self.output2(x)

    