import { createRouter } from "@tanstack/react-router"
import { routeTree } from "./routeTree.gen"
import { ErrorState, NotFoundState, PendingState } from "@/components/page-states"

export function getRouter() {
    const router = createRouter({
        routeTree,
        scrollRestoration: true,
        // The data changes once a day, so a page a user already loaded is good for minutes
        defaultPreload: "intent",
        defaultStaleTime: 5 * 60_000,
        defaultPendingComponent: PendingState,
        defaultErrorComponent: ErrorState,
        defaultNotFoundComponent: () => <NotFoundState />
    })

    return router
}
