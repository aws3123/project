import '@testing-library/jest-dom/vitest'
import { setupServer } from 'msw/node'
import { beforeAll, afterAll, afterEach } from 'vitest'
import { handlers } from './msw/handlers'

export const server = setupServer(...handlers)

beforeAll(() => server.listen())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
