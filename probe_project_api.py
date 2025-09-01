# --- Nom du projet ouvert ---
def get_open_project_name() -> str:
    """
    Retourne le nom du projet Resolve ouvert.
    Lève RuntimeError si aucun projet n'est ouvert.
    """
    # On part du principe que _bootstrap_resolve_api() a déjà été appelé
    from pybmd import Resolve

    resolve = Resolve()
    pm = resolve.get_project_manager()
    project = pm.get_current_project()
    if not project:
        raise RuntimeError("Aucun projet ouvert dans Resolve.")

    # Compat pybmd / API officielle
    try:
        return project.get_name()
    except AttributeError:
        return project.GetName()

# Exemple d'usage (si tu veux juste l’afficher en CLI)
if __name__ == "__main__":
    try:
        print(get_open_project_name())
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
