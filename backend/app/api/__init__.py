from . import (attendance, auth, dashboard, files, hr_lifecycle, hr_perf_pay, leave, oa_documents, oa_misc,
               oa_travel_expense, org, system, workflow)

ROUTERS = [auth.router, system.router, org.router, leave.router, attendance.router, oa_travel_expense.router,
           files.router, oa_misc.router, oa_documents.router, hr_lifecycle.router, hr_perf_pay.router,
           workflow.router, dashboard.router]
