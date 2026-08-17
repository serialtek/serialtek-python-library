from typing import Any, Optional, Type

# Provide some dummy type defs for optgroup. These aren't very good type
# definitions, but clicks decorators are a bit much for the type checker to
# follow anyway.

class OptionGroup: ...

class _OptGroup:
    def group(
        self,
        name: Optional[str] = ...,
        *,
        help: Optional[str] = ...,
        cls: Optional[Type[OptionGroup]] = ...,
        **attrs: Any,
    ) -> Any: ...
    def option(self, *param_decls: Any, **attrs: Any) -> Any: ...

optgroup = _OptGroup()
