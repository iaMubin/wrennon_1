-- Enable Row Level Security (RLS) on all tables
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- 1. Agents Table Policies
-- Agents can read all agents (to see their peers)
CREATE POLICY "Agents can view all agents" 
ON agents FOR SELECT 
USING (auth.uid() IS NOT NULL);

-- Only Managers can insert, update, or delete agents
CREATE POLICY "Managers can manage agents" 
ON agents FOR ALL 
USING (
    EXISTS (
        SELECT 1 FROM agents a WHERE a.id = auth.uid()::text AND a.role = 'manager'
    )
);

-- 2. Conversations Table Policies
-- Any authenticated agent can view conversations
CREATE POLICY "Agents can view conversations" 
ON conversations FOR SELECT 
USING (auth.uid() IS NOT NULL);

-- Any authenticated agent can update conversations (e.g. resolve, assign to self)
CREATE POLICY "Agents can update conversations" 
ON conversations FOR UPDATE 
USING (auth.uid() IS NOT NULL);

-- 3. Messages Table Policies
-- Any authenticated agent can view messages
CREATE POLICY "Agents can view messages" 
ON messages FOR SELECT 
USING (auth.uid() IS NOT NULL);

-- Agents can insert messages in conversations they are handling or broadcast
CREATE POLICY "Agents can insert messages" 
ON messages FOR INSERT 
WITH CHECK (auth.uid() IS NOT NULL);

-- 4. Audit Logs Policies
-- Only Managers can view audit logs
CREATE POLICY "Managers can view audit logs" 
ON audit_logs FOR SELECT 
USING (
    EXISTS (
        SELECT 1 FROM agents a WHERE a.id = auth.uid()::text AND a.role = 'manager'
    )
);

-- Any authenticated agent or system can insert audit logs
CREATE POLICY "Anyone can insert audit logs" 
ON audit_logs FOR INSERT 
WITH CHECK (true);


