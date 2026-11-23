export interface UserVO {
  id: number
  username: string
  displayName: string
  roles: string[]
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResult {
  token: string
  expiresIn: number
  user: UserVO
}
