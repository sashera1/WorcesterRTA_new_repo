def pad_boundry(xlim:tuple[float, float], ylim:tuple[float, float], padding_factor=0.10):
    x_range = xlim[1] - xlim[0]
    y_range = ylim[1] - ylim[0]
    
    padded_xlim = (xlim[0] - (x_range * padding_factor), 
                   xlim[1] + (x_range * padding_factor))
    
    padded_ylim = (ylim[0] - (y_range * padding_factor), 
                   ylim[1] + (y_range * padding_factor))
    
    return padded_xlim,padded_ylim
