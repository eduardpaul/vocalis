import logging
import asyncio
import inspect
from typing import Callable, Optional

logger = logging.getLogger("vocalis.state")

class StateManager:
    def __init__(self, initial_state: str = "IDLE"):
        self._state = initial_state
        self._lock = asyncio.Lock()
        self._hooks = []

    def set_hook(self, hook: Callable[[str, str], None]):
        """Sets/registers the hook called on transition. Signature: hook(old_state, new_state)"""
        self.register_hook(hook)

    def register_hook(self, hook: Callable[[str, str], None]):
        """Registers a hook called on transition."""
        if hook not in self._hooks:
            self._hooks.append(hook)

    def unregister_hook(self, hook: Callable[[str, str], None]):
        """Unregisters a transition hook."""
        if hook in self._hooks:
            self._hooks.remove(hook)

    @property
    def current(self) -> str:
        return self._state

    async def transition(self, to_state: str):
        async with self._lock:
            old_state = self._state
            if old_state == to_state:
                return
            
            valid_states = {"IDLE", "SPEAKING", "LISTENING", "PROCESSING", "CHALLENGING"}
            if to_state not in valid_states:
                raise ValueError(f"Invalid state: {to_state}")

            self._state = to_state
            logger.info(f"System State transition: {old_state} -> {to_state}")
            
            for hook in self._hooks:
                try:
                    if inspect.iscoroutinefunction(hook):
                        await hook(old_state, to_state)
                    else:
                        hook(old_state, to_state)
                except Exception as e:
                    logger.error(f"Error in StateManager transition hook: {e}")

    async def wait_for_idle(self, timeout: float) -> bool:
        """Waits for state to become IDLE. Returns True if IDLE, False if timeout."""
        if self._state == "IDLE":
            return True
        
        start_time = asyncio.get_running_loop().time()
        while self._state != "IDLE":
            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed >= timeout:
                return False
            await asyncio.sleep(0.05)
        return True
