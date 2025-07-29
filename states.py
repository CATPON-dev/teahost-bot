# --- START OF FILE states.py ---
from aiogram.fsm.state import State, StatesGroup

class UserBotSetup(StatesGroup):
    ChoosingUserBotType = State()
    ChoosingServer = State()
    InstallingUserBot = State()
    WaitingForLoginLinkRequest = State()
    MonitoringForRestart = State()
    
    Management = State()
    ConfirmDeleteUserBot = State()
    Migrating = State()
    
    Reinstalling = State()

class UserBotTransfer(StatesGroup):
    WaitingForNewOwnerID = State()
    ConfirmingTransfer = State()

class AdminTasks(StatesGroup):
    WaitingForNote = State()

class UserReview(StatesGroup):
    WaitingForReview = State()
    
class AdminUserBotTransfer(StatesGroup):
    WaitingForNewOwnerID = State()
    ConfirmingTransfer = State()
    
class CommitEditing(StatesGroup):
    WaitingForNewText = State()

class APITokenManagement(StatesGroup):
    TokenHidden = State()
    TokenShown = State()
# --- END OF FILE states.py ---