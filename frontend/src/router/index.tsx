import { createBrowserRouter } from 'react-router-dom'
import App from '../App'
import { SubmitPage } from '../pages/SubmitPage'
import { TaskDashboardPage } from '../pages/TaskDashboardPage'
import { CodeReviewDetailPage } from '../pages/CodeReviewDetailPage'
import { BusinessRiskDetailPage } from '../pages/BusinessRiskDetailPage'
import { BusinessRiskSourcePage } from '../pages/BusinessRiskSourcePage'
import { FeedbackDashboardPage } from '../pages/FeedbackDashboardPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <SubmitPage /> },
      { path: 'tasks', element: <TaskDashboardPage /> },
      { path: 'code-review/:taskId', element: <CodeReviewDetailPage /> },
      { path: 'business-risk/:taskId', element: <BusinessRiskDetailPage /> },
      { path: 'business-risk/source', element: <BusinessRiskSourcePage /> },
      { path: 'feedback', element: <FeedbackDashboardPage /> },
    ],
  },
])
