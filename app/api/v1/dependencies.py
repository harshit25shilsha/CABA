from fastapi import HTTPException, Request, status

from app.api.v1.roles import Role

def get_current_user(request: Request) -> dict:
    """
    Return the authenticated user information
    populated by AuthMiddleware.
    """

    user_id = getattr(request.state, "user_id", None)
    role = getattr(request.state, "role", None)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    if not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User role is missing",
        )

    return {
        "user_id": user_id,
        "role": role,
    }


def require_roles(*allowed_roles: Role):
    """
    Allow access only to users having one
    of the specified roles.
    """

    def dependency(request: Request) -> dict:
        current_user = get_current_user(request)

        role = current_user["role"]

        allowed_values = {
            allowed_role.value
            for allowed_role in allowed_roles
        }

        if role not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )

        return current_user

    return dependency


require_admin = require_roles(Role.ADMIN)

require_ca_or_sub_ca = require_roles(
    Role.CA,
    Role.SUB_CA,
)

require_client = require_roles(Role.CLIENT)